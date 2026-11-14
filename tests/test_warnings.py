"""Warning thresholds protect the user from silent recipe side effects."""

from copy import deepcopy

from catalog import load_data, resolve_recipe
from metrics import totals
from warning_rules import badges, build_warnings


def test_texture_core_salt_and_preservative_warnings():
    """Explicit removals should report structural and preservation consequences."""
    data = load_data()
    original = resolve_recipe({"name": "Example", "tags": ["baking"], "ingredients": [
        {"name": "sugar", "grams": 100}, {"name": "butter", "grams": 100},
        {"name": "salt", "grams": 10}, {"name": "ham", "grams": 50}], "core_ingredients": ["ham"]}, data)
    final = deepcopy(original)
    final["ingredients"] = {}
    repair = {"scores": {"target_reached": True}, "affected_axes": [], "added_compensators": []}
    codes = {row["code"] for row in build_warnings(original, final, [], repair, data)}
    assert {"TEXTURE_RISK_SWEETENER", "MOUTHFEEL_RISK_FAT", "SALT_FUNCTION_RISK",
            "CORE_INGREDIENT_CHANGED", "PRESERVATIVE_REDUCED", "SIDE_EFFECT_WORSENED"} <= codes


def test_badges_use_servings_and_twenty_percent_threshold():
    """Increasing the portion count should remove a high-sugar badge at the boundary."""
    data = load_data()
    amounts = totals({"sugar": 10}, data)
    assert "high-sugar" in badges(amounts, 1, data)
    assert "high-sugar" not in badges(amounts, 2, data)


def test_strict_cut_threshold_and_compensator_caution():
    """A cut exactly at 50% avoids the greater-than-50 rule; caution text is retained."""
    data = load_data()
    original = resolve_recipe({"name": "Example", "tags": ["baking"], "ingredients": [{"name": "sugar", "grams": 100}]}, data)
    final = deepcopy(original)
    final["ingredients"]["sugar"] = 50
    repair = {"scores": {"target_reached": False, "taste_retention_pct": 70}, "affected_axes": ["sweet"],
              "limit_reached": True, "added_compensators": [{"ingredient": "cinnamon", "caution": "Example caution"}]}
    warnings = build_warnings(original, final, [], repair, data, reduce_percent=50)
    codes = {row["code"] for row in warnings}
    assert "TEXTURE_RISK_SWEETENER" not in codes
    assert {"TARGET_MISSED", "COMPENSATION_LIMIT", "COMPENSATOR_CAUTION"} <= codes
    assert warnings[0]["message"] == "Could not reach 95% taste retention at 50% reduction. Achieved 70.0%. Try a lower reduction percentage."
