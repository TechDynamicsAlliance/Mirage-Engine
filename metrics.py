"""Unrounded measurements shared by analysis and the v2 modification algorithm."""

from __future__ import annotations

from catalog import finite_number

IMPLICIT_MAX_CUT = 0.8
MIN_CONTRIBUTION_SHARE = 0.05
LOCKED_ROLES = ("structural", "aromatic")


def contributions(ingredients: dict[str, float], data: dict) -> dict:
    """Measure each ingredient for every metric so totals and later comparisons agree."""
    result = {}
    for group, definitions, content in (
        ("nutrients", "nutrient_defs", "nutrients_per_g"),
        ("chemicals", "chemical_defs", "chemicals_per_g"),
    ):
        result[group] = {}
        for definition in data[definitions]:
            metric = definition["id"]
            result[group][metric] = {}
            for name, grams in ingredients.items():
                per_g = data["ingredients"].get(name, {}).get(content, {}).get(metric, 0.0)
                amount = finite_number(grams * per_g, "custom_recipe.ingredients", "INVALID_RECIPE")
                result[group][metric][name] = amount
    return result


def totals(ingredients: dict[str, float], data: dict) -> dict:
    """Sum all nutrients and chemicals without rounding, avoiding drift across stacked cuts."""
    result = {}
    for group, metrics in contributions(ingredients, data).items():
        result[group] = {
            metric: finite_number(sum(amounts.values()), "custom_recipe.ingredients", "INVALID_RECIPE")
            for metric, amounts in metrics.items()
        }
    return result


def per_serving(amounts: dict, servings: float) -> dict:
    """Divide total amounts by the recipe's validated serving count for portion comparisons."""
    return {group: {metric: amount / servings for metric, amount in values.items()}
            for group, values in amounts.items()}


def taste_vector(ingredients: dict[str, float], data: dict) -> dict[str, float]:
    """Measure all four taste axes so later repair can see what each cut changed."""
    return {
        axis: finite_number(sum(grams * data["ingredients"].get(name, {}).get("taste_per_g", {}).get(axis, 0.0)
                                for name, grams in ingredients.items()),
                            "custom_recipe.ingredients", "INVALID_RECIPE")
        for axis in data["taste_axes"]
    }


def fingerprint(ingredients: dict[str, float], data: dict) -> list[str]:
    """Return sorted unique molecules for present foods, making baseline output deterministic."""
    molecules = set()
    for name, grams in ingredients.items():
        if grams > 0:
            molecules.update(data["ingredients"].get(name, {}).get("molecules", []))
    return sorted(molecules)


def eligible_contributions(recipe: dict, kind: str, target: str, original_total: float,
                           touched: list[str], data: dict) -> dict[str, float]:
    """Find current contributors that can be cut without altering cores, aromatics or user edits.

    The 5% threshold always uses the ORIGINAL total. Current contributions change
    after each edit, so eligibility is recalculated before every metric cut.
    """
    content = "nutrients_per_g" if kind == "nutrient" else "chemicals_per_g"
    eligible = {}
    for name, grams in recipe["ingredients"].items():
        info = data["ingredients"].get(name, {})
        amount = grams * info.get(content, {}).get(target, 0.0)
        if (amount > 0 and amount >= MIN_CONTRIBUTION_SHARE * original_total
                and name not in recipe["core_ingredients"] and name not in touched
                and info.get("role") not in LOCKED_ROLES):
            eligible[name] = amount
    return eligible
