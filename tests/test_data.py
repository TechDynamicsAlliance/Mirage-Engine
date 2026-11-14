"""Checks for data/placeholder_data.json.

These tests lock the catalog before the engine starts trusting it.
Every number in that file is an approximation, so the tests check shape
and consistency, not that a value matches a lab paper.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine import load_data

DATA = load_data()
REQUIRED_DISHES = [
    "lemonade",
    "tomato_soup",
    "butter_chicken",
    "chicken_curry",
    "chocolate_cake",
    "caesar_dressing",
    "instant_noodles",
    "ham_cheese_sandwich",
]
NUTRIENT_IDS = [
    "calories_kcal",
    "fat_g",
    "saturated_fat_g",
    "carbs_g",
    "sugar_g",
    "fiber_g",
    "protein_g",
    "cholesterol_mg",
]
CHEMICAL_IDS = [
    "sodium_mg",
    "msg_g",
    "sodium_benzoate_mg",
    "sodium_nitrite_mg",
    "tartrazine_mg",
    "caffeine_mg",
]
ROLES = {
    "structural",
    "seasoning",
    "fat_source",
    "sweetener",
    "liquid",
    "aromatic",
    "condiment",
    "thickener",
}
# Caps the current engine already relies on. They must survive migration.
ORIGINAL_MAX_G = {
    "vanilla_extract": 3,
    "cinnamon": 3,
    "mint_leaves": 5,
    "tomato_paste": 20,
    "mushroom_powder": 10,
    "lemon_zest": 5,
    "potassium_chloride": 3,
    "yogurt": 50,
    "applesauce": 60,
    "stock_reduction": 30,
}
ORIGINAL_RECIPES = {
    "lemonade": {"sugar": 50, "lemon_juice": 100, "water": 500},
    "tomato_soup": {
        "tomato": 400, "onion": 100, "garlic": 10, "salt": 8,
        "butter": 30, "heavy_cream": 50, "water": 500,
    },
    "butter_chicken": {
        "chicken_breast": 500, "butter": 60, "heavy_cream": 120, "tomato": 300,
        "onion": 150, "garlic": 15, "salt": 12, "garam_masala": 10,
        "chili_powder": 5, "vegetable_oil": 30, "water": 100,
    },
}


def _nutrient(ing: dict, key: str) -> float:
    """Missing nutrient keys mean 0, which is the catalog's own rule."""
    return ing["nutrients_per_g"].get(key, 0.0)


def test_schema_header():
    """The file says it is placeholder schema 2, so nobody treats it as lab data."""
    assert DATA["meta"]["schema_version"] == 2
    assert DATA["meta"]["data_source"] == "placeholder"
    warning = DATA["meta"]["warning"]
    assert "placeholder" in warning
    assert "[VERIFY]" in warning
    assert "approx. % of daily reference" in warning


def test_defs_and_mechanisms():
    """Axes, nutrients, chemicals, and mechanisms are the ones the later phases name."""
    assert DATA["taste_axes"] == ["sweet", "salty", "umami", "richness"]
    assert [row["id"] for row in DATA["nutrient_defs"]] == NUTRIENT_IDS
    assert [row["id"] for row in DATA["chemical_defs"]] == CHEMICAL_IDS
    by_id = {row["id"]: row for row in DATA["chemical_defs"]}
    assert by_id["sodium_benzoate_mg"]["group"] == "preservatives"
    assert by_id["sodium_nitrite_mg"]["group"] == "preservatives"
    assert by_id["tartrazine_mg"]["label"] == "Artificial yellow colour"
    assert by_id["caffeine_mg"]["daily_value"] == 400
    assert by_id["sodium_mg"]["daily_value"] == 2300
    fiber = next(row for row in DATA["nutrient_defs"] if row["id"] == "fiber_g")
    protein = next(row for row in DATA["nutrient_defs"] if row["id"] == "protein_g")
    assert fiber["direction"] == "higher_is_better"
    assert protein["direction"] == "higher_is_better"
    for mechanism in DATA["mechanisms"].values():
        text = mechanism["plain_text"].lower()
        assert "reported" in text
        assert "prove" not in text


def test_catalog_size_and_required_dishes():
    """Eight named dishes, and enough ingredients for the three modules to browse."""
    assert list(DATA["dishes"]) == REQUIRED_DISHES
    assert 45 <= len(DATA["ingredients"]) <= 60


def test_every_dish_ingredient_exists_and_core_is_in_the_dish():
    """A dish cannot name a food the catalog does not have, or a core item it does not use."""
    for slug, dish in DATA["dishes"].items():
        assert dish["servings"] >= 1, slug
        for name in dish["ingredients"]:
            assert name in DATA["ingredients"], f"{slug} uses unknown {name}"
        for core in dish["core_ingredients"]:
            assert core in dish["ingredients"], f"{slug} core {core} is not in the dish"


def test_original_recipes_kept_their_grams():
    """Migration must not rescale the three dishes the current tests cook."""
    for slug, ingredients in ORIGINAL_RECIPES.items():
        assert DATA["dishes"][slug]["ingredients"] == ingredients


def test_aliases_are_unique_across_the_catalog():
    """An alias that points at two foods would make name resolution ambiguous."""
    seen: dict[str, str] = {}
    for name, ing in DATA["ingredients"].items():
        assert isinstance(ing["aliases"], list)
        for alias in ing["aliases"]:
            assert alias not in seen, f"{alias!r} is on both {seen.get(alias)} and {name}"
            assert alias not in DATA["ingredients"], f"{alias!r} is also a real ingredient name"
            seen[alias] = name


def test_nutrient_relationships_and_calories():
    """Sugar sits inside carbs, saturated fat sits inside fat, calories follow the macros.

    The 20% calorie band is the allowed slack. We still expect the 4/4/9 estimate,
    because that is how this placeholder file builds calories.
    """
    for name, ing in DATA["ingredients"].items():
        sugar = _nutrient(ing, "sugar_g")
        carbs = _nutrient(ing, "carbs_g")
        sat = _nutrient(ing, "saturated_fat_g")
        fat = _nutrient(ing, "fat_g")
        protein = _nutrient(ing, "protein_g")
        calories = _nutrient(ing, "calories_kcal")
        assert sugar <= carbs + 1e-9, name
        assert sat <= fat + 1e-9, name
        expected = 4 * protein + 4 * carbs + 9 * fat
        if expected == 0:
            assert calories == 0, name
        else:
            assert abs(calories - expected) / expected <= 0.20, name
        for value in ing["nutrients_per_g"].values():
            assert value >= 0, name
        for value in ing["chemicals_per_g"].values():
            assert value >= 0, name


def test_taste_values_are_non_negative():
    """A negative taste number would invent a deficit. Every axis is present and >= 0."""
    for name, ing in DATA["ingredients"].items():
        taste = ing["taste_per_g"]
        assert set(taste) == {"sweet", "salty", "umami", "richness"}, name
        for value in taste.values():
            assert value >= 0, name


def test_umami_and_richness_were_filled_in():
    """Glutamate-rich foods have umami, and plain fats taste as rich as they are fatty.

    Fat compensators use a smaller richness number: it is a taste boost, not grams of fat.
    """
    for name in ("tomato", "tomato_paste", "mushroom_powder", "chicken_breast", "stock_reduction", "soy_sauce", "parmesan"):
        assert DATA["ingredients"][name]["taste_per_g"]["umami"] > 0, name
    for name in ("butter", "heavy_cream", "vegetable_oil"):
        ing = DATA["ingredients"][name]
        assert ing["taste_per_g"]["richness"] == ing["nutrients_per_g"]["fat_g"]
    for name in ("yogurt", "applesauce", "stock_reduction"):
        ing = DATA["ingredients"][name]
        richness = ing["taste_per_g"]["richness"]
        assert 0 < richness < ing["nutrients_per_g"]["fat_g"] + 0.5
        assert richness != ing["nutrients_per_g"]["fat_g"]


def test_kept_taste_numbers():
    """Sugar's sweetness and mushroom powder's salty boost are the old figures."""
    assert DATA["ingredients"]["sugar"]["taste_per_g"]["sweet"] == 1.0
    assert DATA["ingredients"]["salt"]["taste_per_g"]["salty"] == 1.0
    assert DATA["ingredients"]["mushroom_powder"]["taste_per_g"]["salty"] == 0.6
    assert DATA["ingredients"]["salt"]["chemicals_per_g"]["sodium_mg"] == 388.0


def test_compensators_have_all_fields_and_cover_each_axis():
    """A compensator the ranker cannot read is worse than no compensator.

    Each of sweet, salty, and richness needs 4 options, and umami needs 3,
    so a later repair step has somewhere to look.
    """
    counts = {"sweet": 0, "salty": 0, "umami": 0, "richness": 0}
    mechanisms = DATA["mechanisms"]
    found = set()
    for name, ing in DATA["ingredients"].items():
        assert ing["data_quality"] == "placeholder_approx"
        assert ing["role"] in ROLES
        comp = ing.get("compensator")
        if comp is None:
            continue
        found.add(name)
        for field in ("compensates", "fits", "max_g", "mechanism", "caution"):
            assert field in comp, f"{name} missing {field}"
        assert comp["compensates"], name
        assert comp["fits"], name
        assert comp["max_g"] > 0, name
        assert comp["mechanism"] in mechanisms, name
        assert comp["caution"] is None or isinstance(comp["caution"], str)
        for axis in comp["compensates"]:
            assert axis in counts, name
            counts[axis] += 1
    assert counts["sweet"] >= 4
    assert counts["salty"] >= 4
    assert counts["richness"] >= 4
    assert counts["umami"] >= 3
    for name, max_g in ORIGINAL_MAX_G.items():
        assert name in found
        assert DATA["ingredients"][name]["compensator"]["max_g"] == max_g


def test_packaged_dishes_carry_the_chemical_module():
    """Noodles and ham are in the catalog so chemicals are not all zero.

    Cocoa carries a little caffeine for the same reason.
    """
    sachet = DATA["ingredients"]["seasoning_sachet"]["chemicals_per_g"]
    assert sachet["msg_g"] > 0
    assert sachet["sodium_benzoate_mg"] > 0
    assert sachet["tartrazine_mg"] > 0
    assert DATA["ingredients"]["ham"]["chemicals_per_g"]["sodium_nitrite_mg"] > 0
    assert DATA["ingredients"]["cocoa_powder"]["chemicals_per_g"]["caffeine_mg"] > 0
    assert "seasoning_sachet" in DATA["dishes"]["instant_noodles"]["ingredients"]
    assert "ham" in DATA["dishes"]["ham_cheese_sandwich"]["ingredients"]
    assert "cocoa_powder" in DATA["dishes"]["chocolate_cake"]["ingredients"]


def test_file_matches_what_load_data_returns_and_has_no_nan():
    """load_data is the loader the engine uses, and the file must be plain JSON."""
    path = Path(__file__).resolve().parents[1] / "data" / "placeholder_data.json"
    raw = path.read_text()
    assert json.loads(raw) == DATA
    json.dumps(DATA, allow_nan=False)
