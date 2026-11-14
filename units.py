"""Conservative household-unit conversion; never guess a solid food's density."""
from fractions import Fraction
import re
from catalog import MirageError, finite_number, load_data, resolve_name, suggest_names

UNIT_ALIASES = {"gram": "g", "grams": "g", "kilogram": "kg", "kilograms": "kg", "milligram": "mg",
                "milligrams": "mg", "milliliter": "ml", "milliliters": "ml", "liter": "l", "liters": "l",
                "teaspoon": "tsp", "teaspoons": "tsp", "tablespoon": "tbsp", "tablespoons": "tbsp",
                "cups": "cup", "pieces": "piece", "ounce": "oz", "ounces": "oz", "pound": "lb", "pounds": "lb"}
VOLUME_ML = {"ml": 1, "l": 1000, "tsp": 5, "tbsp": 15, "cup": 240}
MASS_G = {"g": 1, "kg": 1000, "mg": 0.001, "oz": 28.349523125, "lb": 453.59237}
QUANTITY_PATTERN = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"


def parse_quantity(value) -> float:
    """Accept numeric, decimal and fraction quantities without evaluating arbitrary text."""
    if isinstance(value, str):
        value = value.strip()
        if not re.fullmatch(QUANTITY_PATTERN, value):
            raise MirageError("Quantity must be a number or fraction.", "INVALID_RECIPE", "quantity")
        try:
            value = sum(float(Fraction(part)) for part in value.split())
        except (ValueError, ZeroDivisionError, OverflowError):
            raise MirageError("Invalid fraction.", "INVALID_RECIPE", "quantity") from None
    number = finite_number(value, "quantity", "INVALID_RECIPE")
    if number <= 0:
        raise MirageError("Quantity must be positive.", "INVALID_RECIPE", "quantity")
    return number


def to_grams(quantity, unit: str, ingredient: dict | None = None) -> float:
    """Use mass units, explicit portion weights or a declared liquid-density assumption."""
    number = parse_quantity(quantity)
    unit = UNIT_ALIASES.get(unit.strip().lower(), unit.strip().lower())
    info = ingredient or {}
    if unit in MASS_G:
        grams = number * MASS_G[unit]
    elif unit == "piece" and info.get("grams_per_piece"):
        grams = number * info["grams_per_piece"]
    elif unit in VOLUME_ML:
        if info.get("grams_per_cup"):
            grams = number * VOLUME_ML[unit] / 240 * info["grams_per_cup"]
        elif info.get("role") == "liquid" or info.get("category") == "liquid":
            grams = number * VOLUME_ML[unit]
        else:
            raise MirageError("An ingredient-specific volume weight is required.", "MISSING_QUANTITY_DATA", "unit")
    else:
        raise MirageError(f"No supported weight conversion for '{unit}'.", "MISSING_QUANTITY_DATA", "unit")
    return finite_number(grams, "quantity", "INVALID_RECIPE")


def split_ingredient_line(line: str) -> tuple[str, str, str]:
    """Separate a quantity, unit and food name, leaving ambiguous phrases for user correction."""
    matched = re.fullmatch(rf"\s*({QUANTITY_PATTERN})\s+([A-Za-z]+)\s+(.+?)\s*", line)
    if not matched:
        raise MirageError("Use a quantity, unit and ingredient name.", "INVALID_RECIPE", "text")
    return matched.group(1), matched.group(2), matched.group(3)


def parse_ingredient_lines(text: str, servings=1, data=None) -> dict:
    """Turn parseable lines into a custom recipe and report every omitted line explicitly."""
    data = load_data() if data is None else data
    servings = finite_number(servings, "servings", "INVALID_RECIPE")
    if servings < 1:
        raise MirageError("Servings must be at least one.", "INVALID_RECIPE", "servings")
    if not isinstance(text, str):
        raise MirageError("Recipe text must be a string.", "INVALID_RECIPE", "text")
    rows, unresolved, unparsed = [], [], []
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) > 40:
        raise MirageError("Use at most 40 ingredient lines.", "INVALID_RECIPE", "text")
    for line in lines:
        try:
            quantity, unit, entered = split_ingredient_line(line)
            name = resolve_name(entered, data)
            grams = to_grams(quantity, unit, data["ingredients"].get(name, {}))
            rows.append({"name": name or entered, "grams": grams})
            if name is None:
                unresolved.append({"name": entered, "suggestions": suggest_names(entered, data)})
        except MirageError as error:
            unparsed.append({"line": line, "reason": str(error)})
    return {"custom_recipe": {"name": "Custom recipe", "servings": servings, "tags": [], "ingredients": rows},
            "unresolved_ingredients": unresolved, "unparsed_lines": unparsed}
