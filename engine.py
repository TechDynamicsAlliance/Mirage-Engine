"""Public facade for MIRAGE: deterministic recipe analysis and reformulation."""

from __future__ import annotations

import copy
from catalog import DishNotFound, MirageError, finite_number, load_data, load_runtime_data, resolve_recipe
import metrics
from modify import apply_modifications
from taste import repair
from compare import build_response

def analyze_baseline(source: str | dict, data: dict | None = None) -> dict:
    """Resolve a recipe and expose its unrounded baseline for the later v2 steps.

    This Phase 2 shape is internal. Phase 5 will build the frontend detail shape.
    Unknown ingredients stay visible but cannot contribute invented nutrition.
    """
    if data is None:
        data = load_runtime_data()
    if data.get("meta", {}).get("data_source") != "placeholder":
        raise MirageError("A quantitative baseline requires ingredient nutrition and taste measurements. Use analyze for source details.", "DATA_UNAVAILABLE", "data")
    recipe = resolve_recipe(source, data)
    amounts = metrics.totals(recipe["ingredients"], data)
    warnings = [
        {"code": "UNKNOWN_INGREDIENT", "severity": "caution",
         "message": f"Unknown ingredient '{item['name']}': its nutrition is not included in these numbers.",
         "related": [item["name"]]}
        for item in recipe["unresolved_ingredients"]
    ]
    return {"recipe": recipe, "totals": amounts,
            "per_serving": metrics.per_serving(amounts, recipe["servings"]),
            "contributions": metrics.contributions(recipe["ingredients"], data),
            "taste": metrics.taste_vector(recipe["ingredients"], data),
            "fingerprint": metrics.fingerprint(recipe["ingredients"], data),
            "unresolved_ingredients": copy.deepcopy(recipe["unresolved_ingredients"]),
            "warning_details": warnings, "warnings": [row["message"] for row in warnings],
            "data_source": data.get("meta", {}).get("data_source", "unknown")}


def analyze(source: str | dict, data: dict | None = None) -> dict:
    """Build full dish details and slider limits from the same baseline used by reformulation."""
    from detail import build_detail
    if data is None:
        data = load_runtime_data()
    if data.get("meta", {}).get("data_source") != "placeholder":
        from live_service import analyze_live, resolve_live_source
        return analyze_live(resolve_live_source(source, data), data)
    return build_detail(analyze_baseline(source, data), data)


def normalize_options(options: dict | None, recipe: dict) -> dict:
    """Fill defaults and validate options so repair cannot receive unsafe limits."""
    if options is None:
        options = {}
    if not isinstance(options, dict):
        raise MirageError("Options must be an object.", field="options")
    result = {"max_compensators": 3, "exclude_compensators": [], "servings": recipe["servings"], "include_trace": True}
    for key in options:
        if key not in result:
            raise MirageError("Unknown option.", field=f"options.{key}")
    result.update(copy.deepcopy(options))
    maximum = result["max_compensators"]
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 0 <= maximum <= 5:
        raise MirageError("max_compensators must be an integer from 0 to 5.", field="options.max_compensators")
    excluded = result["exclude_compensators"]
    if not isinstance(excluded, list) or any(not isinstance(name, str) or not name.strip() for name in excluded):
        raise MirageError("Use a list of compensator names.", field="options.exclude_compensators")
    if not isinstance(result["include_trace"], bool):
        raise MirageError("include_trace must be true or false.", field="options.include_trace")
    servings = finite_number(result["servings"], "options.servings", "INVALID_REQUEST")
    if servings < 1:
        raise MirageError("Servings must be at least 1.", field="options.servings")
    result["servings"] = servings
    return result


def reformulate(source: str | dict | None = None, modifications=None, options=None,
                data: dict | None = None, *, goal=None, reduce_percent=None, dish=None) -> dict:
    """Resolve, cut, repair and compare a recipe while accepting both v2 and legacy calls."""
    if source is not None and dish is not None:
        raise MirageError("Supply source or dish, not both.", field="dish")
    source = source if source is not None else dish
    if data is None:
        data = load_runtime_data()
    # Legacy positional call: reformulate('lemonade', 'sugar', 20, data).
    if isinstance(modifications, str):
        if goal is not None or reduce_percent is not None:
            raise MirageError("Do not mix positional and keyword legacy goals.", field="goal")
        goal, reduce_percent, modifications, options = modifications, options, None, None
    if data.get("meta", {}).get("data_source") != "placeholder":
        from live_service import reformulate_live, resolve_live_source
        return reformulate_live(resolve_live_source(source, data), modifications, options, data,
                                goal=goal, reduce_percent=reduce_percent)
    if goal is not None:
        if goal not in ("sugar", "salt", "sodium", "fat"):
            raise MirageError("Goal must be sugar, salt, sodium or fat.", field="goal")
        if modifications is not None:
            raise MirageError("Use legacy goals or modifications, not both.", field="modifications")
        percent = finite_number(reduce_percent, "reduce_percent", "PERCENT_OUT_OF_RANGE")
        if not 1 <= percent <= 80:
            raise MirageError("Legacy reduction must be 1 to 80 percent.", "PERCENT_OUT_OF_RANGE", "reduce_percent")
    elif reduce_percent is not None:
        raise MirageError("A legacy percentage requires a goal.", field="goal")
    recipe = resolve_recipe(source, data)
    options_used = normalize_options(options, recipe)
    if goal is not None:
        if goal == "sugar":
            kind, target = ("ingredient", "sugar") if "sugar" in recipe["ingredients"] else ("nutrient", "sugar_g")
        elif goal in ("salt", "sodium"):
            kind, target = ("ingredient", "salt") if "salt" in recipe["ingredients"] else ("chemical", "sodium_mg")
        else:
            kind, target = "nutrient", "fat_g"
        modifications = [{"type": kind, "target": target, "action": "reduce", "percent": percent}]
    cut = apply_modifications(recipe, modifications, data)
    repaired = repair(recipe, cut, options_used, data)
    return build_response(recipe, cut, repaired, options_used, data, goal=goal, reduce_percent=reduce_percent)


def list_dishes(data: dict | None = None) -> list[dict]:
    """Keep the legacy dropdown fields while later endpoints add richer dish metadata."""
    if data is None:
        data = load_runtime_data()
    result = []
    for name, dish in data["dishes"].items():
        detail = analyze(name, data)
        names = [row["name"] for row in detail["ingredients"]]
        goals = [goal for goal in ("sugar", "salt", "fat")
                 if (goal == "fat" and data["meta"]["data_source"] == "placeholder") or goal in names]
        result.append({"dish": name, "goals": goals,
                       "ingredients": names, "display_name": detail["display_name"],
                       "servings": detail["servings"], "tags": detail["tags"], "badges": detail["badges"],
                       "baseline": {f"{key}_per_serving": detail["per_serving"][group][key]
                                    for group, key in (("nutrients", "calories_kcal"), ("chemicals", "sodium_mg"),
                                                       ("nutrients", "sugar_g"), ("nutrients", "fat_g"))}})
    return result
