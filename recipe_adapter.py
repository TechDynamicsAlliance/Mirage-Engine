"""Pure conversion from observed RecipeDB responses into engine recipes."""
from dataclasses import dataclass, field, asdict
from copy import deepcopy
import re
from catalog import MirageError, resolve_name
from units import parse_quantity, to_grams, split_ingredient_line


@dataclass
class Recipe:
    """Carry explicit ingredient grams and unresolved quantities without performing I/O."""
    name: str
    servings: float
    tags: list[str]
    ingredients: list[dict]
    core_ingredients: list[str]
    source_metadata: dict = field(default_factory=dict)
    unresolved_quantities: list[dict] = field(default_factory=list)

    def to_dict(self):
        """Return a detached dictionary usable by the existing engine entry points."""
        return asdict(self)


def recipe_payload(payload: dict) -> dict:
    """Unwrap both documented and observed envelopes without losing sibling ingredients."""
    body = payload.get("payload", payload)
    if isinstance(body.get("data"), dict) and "ingredients" in body["data"]:
        body = body["data"]
    if "recipe" not in body and "ingredients" in body and isinstance(body.get("data"), dict):
        body = {**body, "recipe": body["data"]}
    if not isinstance(body.get("recipe"), dict) or not isinstance(body.get("ingredients"), list):
        raise MirageError("RecipeDB response has no recipe and ingredient list.", "UPSTREAM_INVALID_RESPONSE", "recipe")
    return deepcopy(body)


def recipedb_to_recipe(payload: dict, data: dict, *, servings: float | None = None) -> Recipe:
    """Convert {recipe:{Recipe_id,Recipe_title,...}, ingredients:[{ingredient,quantity,unit,state,ing_id,ndb_id}]}.

    Supports observed data and documented payload envelopes. Household conversions
    require catalog weights. Original ingredient phrases can repair malformed unit
    fields, but failed conversions are reported instead of fabricated or hidden.
    """
    body = recipe_payload(payload)
    metadata = body["recipe"]
    name = str(metadata.get("Recipe_title", "Imported recipe"))
    source_notes = []
    if servings is None:
        raw_servings = str(metadata.get("servings", ""))
        if re.fullmatch(r"\d+(?:\.\d+)?", raw_servings):
            servings = parse_quantity(raw_servings)
        else:
            servings = 1
            source_notes.append(f"Source yield '{raw_servings}' is not a numeric serving count; showing the whole recipe as one serving.")
    servings = parse_quantity(servings)
    if servings < 1:
        raise MirageError("Servings must be at least one.", "INVALID_RECIPE", "servings")
    tags = [tag for tag in ("soup", "curry", "salad", "dressing", "sandwich", "noodle", "stew", "sauce", "beverage")
            if tag in name.lower()]
    if any(word in name.lower() for word in ("cake", "cookie", "bread", "muffin", "brownie")):
        tags += ["baking", "dessert"]
    ingredients, unresolved, cores = [], [], []
    for index, row in enumerate(body["ingredients"]):
        entered = str(row.get("ingredient", "")).strip()
        name_key = resolve_name(entered, data) or entered
        info = data["ingredients"].get(name_key, {})
        try:
            if not entered:
                raise MirageError("Ingredient name is missing.", "INVALID_RECIPE", "ingredient")
            if "grams" in row:
                grams = to_grams(row["grams"], "g", info)
            else:
                quantity, unit = row.get("quantity", ""), row.get("unit", "")
                try:
                    grams = to_grams(quantity, unit, info)
                except MirageError:
                    # Upstream may incorrectly report unit='1/2'; the original phrase is evidence.
                    phrase = row.get("ingredient_Phrase", "") or f"{quantity} {entered}"
                    quantity, unit, _ = split_ingredient_line(phrase)
                    grams = to_grams(quantity, unit, info)
            ingredients.append({"name": name_key, "grams": grams})
            if row.get("M_or_A") == "M" or info.get("role") == "structural":
                cores.append(name_key)
        except MirageError as error:
            unresolved.append({"index": index, "ingredient": entered, "quantity": row.get("quantity"),
                               "unit": row.get("unit"), "phrase": row.get("ingredient_Phrase"), "reason": str(error)})
    return Recipe(name, servings, list(dict.fromkeys(tags)), ingredients, list(dict.fromkeys(cores)),
                  {"data_source": "recipedb", "recipe_id": str(metadata.get("Recipe_id", "")),
                   "source_recipe": metadata, "notes": source_notes}, unresolved)
