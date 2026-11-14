"""MIRAGE HTTP API; pure calculations stay in the engine modules."""
from copy import deepcopy
from fastapi import FastAPI, Query
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from engine import analyze, reformulate, list_dishes, load_data, MirageError
from schemas import AnalyzeRequest, ReformulateRequest, ParseRecipeRequest
from units import parse_ingredient_lines
from catalog import load_runtime_data
from foodoscope_client import FoodoscopeClient, unwrap
from live_service import analyze_live, reformulate_live, enrich_recipe, resolve_live_source

app = FastAPI(title="MIRAGE API", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
DATA = load_runtime_data()
UPSTREAM = FoodoscopeClient()


def live_record(request):
    """Resolve saved/live sources before calculation without silently falling back to demo data."""
    if request.recipe_id is not None:
        key = "recipedb_" + request.recipe_id
        if key in DATA["dishes"] and "payload" in DATA["dishes"][key]:
            return DATA["dishes"][key]
        return enrich_recipe(UPSTREAM.recipe(request.recipe_id), UPSTREAM)
    if request.dish is not None:
        record = DATA["dishes"].get(request.dish)
        if record is None:
            from catalog import DishNotFound
            raise DishNotFound(f"Dish '{request.dish}' not found.")
        return record if "payload" in record else None
    if DATA["meta"]["data_source"] == "placeholder":
        return None
    return resolve_live_source(request.custom_recipe, DATA)


@app.exception_handler(MirageError)
async def domain_error(request, error):
    """Expose stable error fields without internal tracebacks or credentials."""
    status = 404 if error.code == "DISH_NOT_FOUND" else 422
    if error.code.startswith("UPSTREAM_") or error.code in ("API_NOT_CONFIGURED", "API_BUDGET_EXCEEDED"):
        status = 503
    return JSONResponse(status_code=status, content={"error": {"code": error.code, "message": str(error), "field": error.field}})


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    """Translate FastAPI validation into the engine's consistent error envelope."""
    first = error.errors()[0]
    field = ".".join(str(part) for part in first["loc"] if part != "body") or "body"
    return JSONResponse(status_code=422, content={"error": {"code": "INVALID_REQUEST", "message": first["msg"], "field": field}})


@app.exception_handler(HTTPException)
async def http_error(request, error):
    """Give missing routes and other framework failures the same response structure."""
    return JSONResponse(status_code=error.status_code, content={"error": {"code": "INVALID_REQUEST", "message": str(error.detail), "field": None}})


@app.get("/health")
def health():
    """Keep the original health payload so existing deployment checks still work."""
    return {"status": "ok", "engine": "mirage", "version": "1.0.0"}


@app.get("/api/meta")
def metadata():
    """Publish metric definitions and limits so the frontend avoids duplicating rules."""
    return {"version": "2.0.0", **{key: deepcopy(DATA[key]) for key in ("taste_axes", "nutrient_defs", "chemical_defs", "mechanisms")},
            "limits": {"ingredient_reduce": [1, 99], "nutrient_reduce": [1, 80], "chemical_reduce": [1, 80],
                       "max_modifications": 8, "max_compensators": 5}, "data_source": DATA["meta"]["data_source"],
            "capabilities": {"ingredient_edits": True, "nutrient_edits": DATA["meta"]["data_source"] == "placeholder",
                             "quantitative_taste_repair": DATA["meta"]["data_source"] == "placeholder",
                             "demo_mode": DATA["meta"]["data_source"] == "placeholder"}}


@app.get("/api/dishes")
def get_dishes():
    """List available dish summaries for the recipe picker."""
    if DATA["meta"]["data_source"] == "placeholder":
        return list_dishes(DATA)
    result = []
    for record in DATA["dishes"].values():
        detail = analyze_live(record, DATA)
        result.append({"dish": detail["dish"], "recipe_id": detail["recipe_id"], "display_name": detail["display_name"],
                       "servings": detail["servings"], "tags": detail["tags"], "badges": detail["badges"],
                       "goals": [goal for goal in ("sugar", "salt") if any(row["name"] == goal for row in detail["ingredients"])],
                       "ingredients": [row["name"] for row in detail["ingredients"]],
                       "baseline": {f"{key}_per_serving": detail["per_serving"][group][key]
                                    for group, key in (("nutrients", "calories_kcal"), ("chemicals", "sodium_mg"),
                                                       ("nutrients", "sugar_g"), ("nutrients", "fat_g"))},
                       "data_source": detail["data_source"], "data_quality": detail["data_quality"]})
    return result


@app.get("/api/dishes/{dish}")
def dish_detail(dish: str):
    """Show ingredient amounts and feasible reductions for one dish."""
    record = live_record(AnalyzeRequest(dish=dish))
    return analyze_live(record, DATA) if record else analyze(dish, DATA)


@app.post("/api/analyze")
def do_analyze(request: AnalyzeRequest):
    """Analyze a dish or a custom recipe without applying changes."""
    record = live_record(request)
    return analyze_live(record, DATA) if record else analyze(request.dish if request.dish is not None else request.custom_recipe, DATA)


@app.get("/api/ingredients")
def ingredients(q: str = "", category: str | None = None, limit: int = Query(20, ge=1, le=100)):
    """Search catalog names, labels and aliases for autocomplete in stable catalog order."""
    needle = q.casefold().replace("_", " ").replace("-", " ")
    result = []
    for name, item in DATA["ingredients"].items():
        labels = [name, item["display_name"], *item.get("aliases", [])]
        if category is not None and item.get("category") != category:
            continue
        if any(needle in label.casefold().replace("_", " ").replace("-", " ") for label in labels):
            result.append({"name": name, **{key: deepcopy(item.get(key)) for key in ("display_name", "category", "role", "aliases")}})
        if len(result) == limit:
            break
    return result


@app.post("/api/reformulate")
def do_reformulate(request: ReformulateRequest):
    """Run the same pure pipeline for v2 and legacy HTTP requests."""
    record = live_record(request)
    if record:
        return reformulate_live(record, request.modifications, request.options, DATA,
                                goal=request.goal, reduce_percent=request.reduce_percent)
    return reformulate(request.dish if request.dish is not None else request.custom_recipe,
                       request.modifications, request.options, DATA, goal=request.goal, reduce_percent=request.reduce_percent)


@app.post("/api/parse-recipe")
def parse_recipe(request: ParseRecipeRequest):
    """Preview parsed grams and unresolved lines before the user submits custom analysis."""
    return parse_ingredient_lines(request.text, request.servings, DATA)


@app.get("/api/recipes/random")
def random_recipe():
    """Select a real recipe upstream, then enrich and analyze its original quantities."""
    chosen = unwrap(UPSTREAM.random_recipe())
    if isinstance(chosen, list):
        chosen = chosen[0] if chosen else {}
    if not isinstance(chosen, dict) or "Recipe_id" not in chosen:
        raise MirageError("Random recipe response omitted its ID.", "UPSTREAM_INVALID_RESPONSE", "recipe_id")
    return analyze_live(enrich_recipe(UPSTREAM.recipe(chosen["Recipe_id"]), UPSTREAM), DATA)


@app.get("/api/recipes/search")
def search_recipes(q: str = Query(..., min_length=1, max_length=200)):
    """Expose RecipeDB title search without downloading the full recipe catalog."""
    return UPSTREAM.search(q)


@app.get("/api/recipes/{recipe_id}")
def imported_recipe(recipe_id: str):
    """Fetch or reuse cached details and molecule associations for a real recipe ID."""
    record = live_record(AnalyzeRequest(recipe_id=recipe_id))
    return analyze_live(record, DATA)
