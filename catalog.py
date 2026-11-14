"""Local catalog loading and recipe resolution; no network or fuzzy substitutions."""

from __future__ import annotations

from copy import deepcopy
from difflib import get_close_matches
import json
import math
import os
from pathlib import Path

MAX_INGREDIENTS = 40


class MirageError(Exception):
    """Carry a code and field so later API handlers can explain invalid requests."""

    def __init__(self, message: str, code: str = "INVALID_REQUEST", field: str | None = None):
        """Keep the usual exception message while adding machine-readable context."""
        super().__init__(message)
        self.code = code
        self.field = field


class DishNotFound(MirageError):
    """Keep the existing exception type so callers can still handle missing dishes."""

    def __init__(self, message: str, field: str = "dish"):
        """Assign the missing-dish code so the API can choose HTTP 404."""
        super().__init__(message, "DISH_NOT_FOUND", field)


def load_data(path: str | Path | None = None) -> dict:
    """Read a fresh local catalog, avoiding a shared mutable data cache."""
    if path is None:
        path = Path(__file__).parent / "data" / "placeholder_data.json"
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_runtime_data() -> dict:
    """Use sourced data by default; labelled demo data requires an explicit environment choice."""
    filename = "placeholder_data.json" if os.environ.get("MIRAGE_DATA_MODE") == "demo" else "live_data.json"
    return load_data(Path(__file__).parent / "data" / filename)


def finite_number(value: object, field: str, code: str) -> float:
    """Reject non-numbers and overflow so invalid inputs cannot produce NaN or infinity."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MirageError("Expected a finite number.", code, field)
    try:
        number = float(value)
    except OverflowError:
        raise MirageError("Number is too large.", code, field) from None
    if not math.isfinite(number):
        raise MirageError("Expected a finite number.", code, field)
    return number


def normalize_name(name: str) -> str:
    """Normalize case, spaces, hyphens and a final 's' for simple name matching."""
    normalized = "_".join(name.strip().lower().replace("-", " ").split())
    return normalized[:-1] if normalized.endswith("s") else normalized


def resolve_name(name: str, data: dict) -> str | None:
    """Try exact names, then aliases, then normalized names; never accept a fuzzy guess."""
    catalog = data["ingredients"]
    if name in catalog:
        return name
    for canonical, item in catalog.items():
        if name in item.get("aliases", []):
            return canonical
    normalized = normalize_name(name)
    for canonical, item in catalog.items():
        if any(normalize_name(label) == normalized
               for label in [canonical, *item.get("aliases", [])]):
            return canonical
    return None


def suggest_names(name: str, data: dict) -> list[str]:
    """Return up to three catalog suggestions so a user can correct an unknown food."""
    labels = {}
    for canonical, item in data["ingredients"].items():
        for label in [canonical, *item.get("aliases", [])]:
            labels[normalize_name(label)] = canonical
    matches = get_close_matches(normalize_name(name), sorted(labels), n=len(labels), cutoff=0.6)
    suggestions = []
    for match in matches:
        if labels[match] not in suggestions:
            suggestions.append(labels[match])
        if len(suggestions) == 3:
            break
    return suggestions


def _text(value: object, field: str) -> str:
    """Require non-empty recipe text to give malformed input a useful field path."""
    if not isinstance(value, str) or not value.strip():
        raise MirageError("Expected non-empty text.", "INVALID_RECIPE", field)
    return value.strip()


def _text_list(value: object, field: str) -> list[str]:
    """Validate recipe lists so tags and core names cannot accidentally be plain strings."""
    if not isinstance(value, list):
        raise MirageError("Expected a list of names.", "INVALID_RECIPE", field)
    return [_text(item, f"{field}[{index}]") for index, item in enumerate(value)]


def resolve_recipe(source: str | dict, data: dict) -> dict:
    """Copy and validate a dish or custom recipe, retaining unknown foods as zero contributors.

    Repeated names or aliases are combined in their first position. An explicit
    empty core list is respected; omitted cores default to structural ingredients.
    """
    if isinstance(source, str):
        if source not in data.get("dishes", {}):
            raise DishNotFound(f"Dish '{source}' not found.")
        dish = deepcopy(data["dishes"][source])
        raw = {
            "name": dish.get("display_name", source),
            "servings": dish.get("servings", 1),
            "tags": dish.get("tags", []),
            "ingredients": [{"name": name, "grams": grams}
                            for name, grams in dish["ingredients"].items()],
            "core_ingredients": dish.get("core_ingredients", []),
        }
        dish_id = source
    elif isinstance(source, dict):
        raw = deepcopy(source)
        dish_id = raw.get("name")
    else:
        raise MirageError("Supply a dish slug or custom recipe.", "INVALID_RECIPE", "custom_recipe")

    name = _text(raw.get("name"), "custom_recipe.name")
    servings = finite_number(raw.get("servings", 1), "custom_recipe.servings", "INVALID_RECIPE")
    if servings < 1:
        raise MirageError("Servings must be at least 1.", "INVALID_RECIPE", "custom_recipe.servings")
    tags = _text_list(raw.get("tags", []), "custom_recipe.tags")
    rows = raw.get("ingredients")
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_INGREDIENTS:
        raise MirageError("Use 1 to 40 ingredients.", "INVALID_RECIPE", "custom_recipe.ingredients")

    ingredients = {}
    unresolved = []
    for index, row in enumerate(rows):
        field = f"custom_recipe.ingredients[{index}]"
        if not isinstance(row, dict):
            raise MirageError("Expected an ingredient object.", "INVALID_RECIPE", field)
        entered_name = _text(row.get("name"), field + ".name")
        grams = finite_number(row.get("grams"), field + ".grams", "INVALID_RECIPE")
        if grams <= 0:
            raise MirageError("Grams must be greater than zero.", "INVALID_RECIPE", field + ".grams")
        canonical = resolve_name(entered_name, data)
        key = canonical or entered_name
        if canonical is None and key not in ingredients:
            unresolved.append({"name": key, "suggestions": suggest_names(key, data)})
        ingredients[key] = ingredients.get(key, 0.0) + grams
    finite_number(sum(ingredients.values()), "custom_recipe.ingredients", "INVALID_RECIPE")

    if "core_ingredients" in raw:
        cores = []
        for index, core in enumerate(_text_list(raw["core_ingredients"], "custom_recipe.core_ingredients")):
            canonical = resolve_name(core, data) or core
            if canonical not in ingredients:
                raise MirageError("A core ingredient must be in the recipe.", "INVALID_RECIPE",
                                  f"custom_recipe.core_ingredients[{index}]")
            if canonical not in cores:
                cores.append(canonical)
    else:
        cores = [key for key in ingredients
                 if data["ingredients"].get(key, {}).get("role") == "structural"]

    return {"dish": dish_id if isinstance(source, str) else name, "name": name,
            "servings": servings, "tags": tags, "ingredients": ingredients,
            "core_ingredients": cores, "unresolved_ingredients": unresolved}
