"""Phase 2 checks: local analysis, validated edits and proportional cuts before repair."""

from copy import deepcopy
import json

import pytest

from catalog import resolve_name, resolve_recipe
from engine import DishNotFound, MirageError, analyze, load_data
from metrics import totals
from modify import apply_modifications, finalize_modification_results, parse_modifications


@pytest.fixture(scope="module")
def data():
    """Load the local catalog once so tests exercise the real placeholder recipes."""
    return load_data()


def edit(kind, target, percent=30, action="reduce", **extra):
    """Build readable requests so each test highlights the behavior it is checking."""
    return {"type": kind, "target": target, "action": action, "percent": percent, **extra}


def run(source, edits, data):
    """Run the Phase 2 pipeline, keeping taste repair out of cut-specific assertions."""
    return apply_modifications(analyze(source, data)["recipe"], edits, data)


@pytest.mark.parametrize("entered,expected", [
    ("sugar", "sugar"), ("white_sugar", "sugar"), (" WHITE-SUGARS ", "sugar"),
    ("chickens", "chicken_breast"), ("Egg Yolks", "egg_yolk"), ("sugra", None),
])
def test_name_resolution_does_not_accept_fuzzy_guesses(entered, expected, data):
    """Exact, alias and simple normalized names resolve; misspellings remain unknown."""
    assert resolve_name(entered, data) == expected


def test_analyze_baseline_and_unknown_contributions(data):
    """An unknown stays visible with suggestions, while totals include only known foods."""
    source = {"name": "My drink", "servings": 2, "ingredients": [
        {"name": "sugar", "grams": 20}, {"name": "water", "grams": 100},
        {"name": "sugra", "grams": 7},
    ]}
    result = analyze(source, data)
    assert result["recipe"]["ingredients"]["sugra"] == 7
    assert result["totals"]["nutrients"]["sugar_g"] == 20
    assert result["per_serving"]["nutrients"]["sugar_g"] == 10
    assert result["taste"] == {"sweet": 20, "salty": 0, "umami": 0, "richness": 0}
    assert result["fingerprint"] == sorted(data["ingredients"]["sugar"]["molecules"])
    unknown = result["unresolved_ingredients"][0]
    assert unknown["name"] == "sugra"
    assert "sugar" in unknown["suggestions"]
    assert 1 <= len(unknown["suggestions"]) <= 3
    assert result["warning_details"][0]["code"] == "UNKNOWN_INGREDIENT"
    assert "its nutrition is not included" in result["warnings"][0]
    for group in ("nutrients", "chemicals"):
        for metric, amounts in result["contributions"][group].items():
            assert amounts["sugra"] == 0
            assert sum(amounts.values()) == pytest.approx(result["totals"][group][metric])
    json.dumps(result, allow_nan=False)


def test_duplicate_aliases_merge_without_rounding_and_cores_default(data):
    """Alias rows combine without losing precision; structural foods become default cores."""
    source = {"name": "Custom", "ingredients": [
        {"name": "chicken", "grams": 100}, {"name": "chicken_breast", "grams": 12.345},
        {"name": "white_sugar", "grams": 0.12345},
    ]}
    result = analyze(source, data)
    assert result["recipe"]["ingredients"] == {"chicken_breast": 112.345, "sugar": 0.12345}
    assert result["recipe"]["core_ingredients"] == ["chicken_breast"]
    assert result["recipe"]["servings"] == 1
    assert result["recipe"]["tags"] == []
    # Phase 5 rounds public detail output; calculation helpers retain full precision.
    assert result["totals"]["nutrients"]["sugar_g"] == 0.12
    assert totals(result["recipe"]["ingredients"], data)["nutrients"]["sugar_g"] == 0.12345
    source["core_ingredients"] = []
    assert resolve_recipe(source, data)["core_ingredients"] == []
    source["core_ingredients"] = ["chicken"]
    assert resolve_recipe(source, data)["core_ingredients"] == ["chicken_breast"]


@pytest.mark.parametrize("source,field", [
    ({"name": "Empty", "ingredients": []}, "custom_recipe.ingredients"),
    ({"name": "Many", "ingredients": [{"name": "water", "grams": 1}] * 41}, "custom_recipe.ingredients"),
    ({"ingredients": [{"name": "water", "grams": 1}]}, "custom_recipe.name"),
    ({"name": "Bad", "ingredients": [None]}, "custom_recipe.ingredients[0]"),
    ({"name": "Bad", "ingredients": [{"name": "", "grams": 1}]}, "custom_recipe.ingredients[0].name"),
    ({"name": "Bad", "ingredients": [{"name": "water", "grams": 1}], "servings": 0}, "custom_recipe.servings"),
    ({"name": "Bad", "ingredients": [{"name": "water", "grams": 1}], "tags": "drink"}, "custom_recipe.tags"),
    ({"name": "Bad", "ingredients": [{"name": "water", "grams": 1}], "core_ingredients": ["sugar"]},
     "custom_recipe.core_ingredients[0]"),
])
def test_invalid_recipe_fields(source, field, data):
    """Reject malformed recipes with a stable code and the field a user needs to fix."""
    with pytest.raises(MirageError) as error:
        analyze(source, data)
    assert error.value.code == "INVALID_RECIPE"
    assert error.value.field == field


@pytest.mark.parametrize("grams", [0, -1, True, "20", None, float("nan"), float("inf"), 10 ** 400, 1e308])
def test_unsafe_grams_never_reach_output(grams, data):
    """Invalid numbers and overflowing nutrition fail instead of leaking non-finite JSON."""
    with pytest.raises(MirageError) as error:
        analyze({"name": "Bad", "ingredients": [{"name": "salt", "grams": grams}]}, data)
    assert error.value.code == "INVALID_RECIPE"


def test_missing_dish_keeps_old_exception_and_adds_error_metadata(data):
    """Old callers can still catch DishNotFound, while v2 gets a code and field."""
    with pytest.raises(DishNotFound) as error:
        analyze("pizza", data)
    assert error.value.code == "DISH_NOT_FOUND"
    assert error.value.field == "dish"


def test_thirty_percent_fat_cut_and_locked_roles(data):
    """A feasible 30% fat target is reached without cutting structural foods or aromatics."""
    result = run("butter_chicken", [edit("nutrient", "fat_g")], data)
    outcome = result["modification_results"][0]
    assert outcome["achieved_percent"] == pytest.approx(30, abs=1)
    assert outcome["status"] == "met"
    original = data["dishes"]["butter_chicken"]
    for name, grams in original["ingredients"].items():
        if name in original["core_ingredients"] or data["ingredients"][name]["role"] in ("structural", "aromatic"):
            assert result["recipe"]["ingredients"][name] == grams


def test_explicit_remove_and_reduce_are_applied_before_metric_cuts(data):
    """Ingredient requests run first even when listed later, and then lock their foods."""
    result = run("butter_chicken", [
        edit("nutrient", "fat_g", 70, id="fat"),
        edit("ingredient", "butter", 30, id="butter"),
        edit("ingredient", "heavy_cream", action="remove", id="cream"),
    ], data)
    assert result["recipe"]["ingredients"]["butter"] == 42
    assert "heavy_cream" not in result["recipe"]["ingredients"]
    assert result["touched_ingredients"] == ["butter", "heavy_cream"]
    assert [row["id"] for row in result["modification_results"]] == ["fat", "butter", "cream"]
    assert result["trace_detail"][0]["text"].startswith("butter:")
    assert result["modification_results"][2]["requested_percent"] is None
    assert result["modification_results"][2]["achieved_percent"] == 100


def test_already_satisfied_and_partial_credit_use_original_totals(data):
    """An earlier ingredient edit can satisfy a target; partial credit avoids over-cutting."""
    satisfied = run("lemonade", [edit("ingredient", "sugar", 40), edit("nutrient", "sugar_g", 30)], data)
    row = satisfied["modification_results"][1]
    assert row["status"] == "already_satisfied"
    assert row["affected_ingredients"] == []
    source = {"name": "Two fats", "ingredients": [
        {"name": "butter", "grams": 100}, {"name": "vegetable_oil", "grams": 100},
    ]}
    partial_credit = run(source, [edit("ingredient", "butter", 20), edit("nutrient", "fat_g", 30)], data)
    assert partial_credit["recipe"]["ingredients"]["butter"] == 80
    # Baseline fat = 181 g; butter already saved 16.2 g of the requested 54.3 g.
    assert partial_credit["recipe"]["ingredients"]["vegetable_oil"] == 61.9
    assert partial_credit["modification_results"][1]["achieved_percent"] == pytest.approx(30)


def test_stacked_metrics_follow_request_order(data):
    """A later sugar target sees savings from the earlier carbohydrate cut."""
    result = run("lemonade", [edit("nutrient", "carbs_g", 50), edit("nutrient", "sugar_g", 30)], data)
    assert result["modification_results"][1]["status"] == "already_satisfied"
    assert result["recipe"]["ingredients"]["lemon_juice"] == 100
    assert result["recipe"]["ingredients"]["sugar"] == pytest.approx(21.6, abs=0.1)


def test_chemical_group_expands_only_present_members(data):
    """Group members retain traceable IDs, and absent chemicals do not become fake edits."""
    source = {"name": "Packaged example", "ingredients": [
        {"name": "seasoning_sachet", "grams": 10}, {"name": "ham", "grams": 50},
    ]}
    result = run(source, [edit("chemical", "preservatives", id="pres")], data)
    assert [row["id"] for row in result["modification_results"]] == [
        "pres.sodium_benzoate_mg", "pres.sodium_nitrite_mg",
    ]
    assert result["modification_results"][0]["status"] == "met"
    assert result["modification_results"][1]["status"] == "not_possible"
    assert result["recipe"]["ingredients"]["ham"] == 50
    noodles = run("instant_noodles", [edit("chemical", "preservatives")], data)
    assert [row["id"] for row in noodles["modification_results"]] == ["m1.sodium_benzoate_mg"]


@pytest.mark.parametrize("target", ["sodium", "salt", "sodium_mg"])
def test_chemical_aliases_and_core_locks(target, data):
    """All sodium names share one metric, with core and aromatic ingredients protected."""
    result = run("caesar_dressing", [edit("chemical", target)], data)
    assert result["modifications"][0]["target"] == "sodium_mg"
    for name in ("parmesan", "anchovy", "garlic", "black_pepper"):
        assert result["recipe"]["ingredients"][name] == data["dishes"]["caesar_dressing"]["ingredients"][name]


@pytest.mark.parametrize("edits,code,field", [
    ([edit("ingredient", "butter")], "UNKNOWN_INGREDIENT_TARGET", "modifications[0].target"),
    ([edit("nutrient", "unlisted")], "UNKNOWN_NUTRIENT", "modifications[0].target"),
    ([edit("chemical", "unlisted")], "UNKNOWN_CHEMICAL", "modifications[0].target"),
    ([edit("chemical", "preservatives")], "TARGET_NOT_PRESENT", "modifications[0].target"),
    ([edit("chemical", "caffeine_mg")], "TARGET_NOT_PRESENT", "modifications[0].target"),
    ([edit("nutrient", "cholesterol_mg")], "TARGET_NOT_PRESENT", "modifications[0].target"),
    ([edit("ingredient", "sugar"), edit("ingredient", "white_sugar")], "DUPLICATE_MODIFICATION", "modifications[1].target"),
    ([edit("chemical", "salt"), edit("chemical", "sodium")], "DUPLICATE_MODIFICATION", "modifications[1].target"),
    ([edit("chemical", "sodium_mg", action="remove")], "INVALID_REQUEST", "modifications[0].action"),
    ([edit("nutrient", "sugar_g", 81)], "PERCENT_OUT_OF_RANGE", "modifications[0].percent"),
    ([edit("chemical", "sodium_mg", 81)], "PERCENT_OUT_OF_RANGE", "modifications[0].percent"),
    ([edit("ingredient", "sugar", 100)], "PERCENT_OUT_OF_RANGE", "modifications[0].percent"),
    ([edit("ingredient", "sugar", float("nan"))], "PERCENT_OUT_OF_RANGE", "modifications[0].percent"),
    ([edit("ingredient", "sugar", True)], "PERCENT_OUT_OF_RANGE", "modifications[0].percent"),
    ([edit("ingredient", "sugar")] * 9, "TOO_MANY_MODIFICATIONS", "modifications"),
    ({}, "INVALID_REQUEST", "modifications"),
    ([None], "INVALID_REQUEST", "modifications[0]"),
    ([edit("ingredient", "sugar", id="same"), edit("ingredient", "water", id="same")],
     "INVALID_REQUEST", "modifications[1].id"),
])
def test_invalid_modifications_have_specific_errors(edits, code, field, data):
    """Catch invalid requests at parsing time rather than silently applying a different edit."""
    with pytest.raises(MirageError) as error:
        run("lemonade", edits, data)
    assert error.value.code == code
    assert error.value.field == field


def test_group_duplicates_and_request_count(data):
    """Expanded members participate in duplicate checks but do not consume extra request slots."""
    recipe = resolve_recipe("instant_noodles", data)
    with pytest.raises(MirageError) as error:
        parse_modifications([edit("chemical", "preservatives"), edit("chemical", "sodium_benzoate_mg")], recipe, data)
    assert error.value.code == "DUPLICATE_MODIFICATION"
    recipe = resolve_recipe({"name": "Packaged", "ingredients": [
        {"name": "ham", "grams": 50}, {"name": "seasoning_sachet", "grams": 10},
    ]}, data)
    requests = [edit("chemical", "preservatives")] + [
        edit("nutrient", key) for key in (
            "calories_kcal", "fat_g", "saturated_fat_g", "carbs_g", "sugar_g", "fiber_g", "protein_g")
    ]
    assert len(parse_modifications(requests, recipe, data)) == 9


def test_impossible_and_capped_cuts_warn(data):
    """Unreachable requests report partial or not_possible with a reason instead of altering cores."""
    impossible = run("ham_cheese_sandwich", [edit("chemical", "sodium_nitrite_mg")], data)
    assert impossible["modification_results"][0]["status"] == "not_possible"
    assert impossible["warning_details"][0]["code"] == "PARTIAL_MODIFICATION"
    assert "locked" in impossible["warnings"][0]
    capped = run("instant_noodles", [edit("chemical", "msg_g", 10), edit("chemical", "sodium_mg", 80)], data)
    assert capped["recipe"]["ingredients"]["instant_noodle_cake"] == 75
    assert capped["recipe"]["ingredients"]["seasoning_sachet"] == 1.4
    assert capped["modification_results"][1]["status"] == "partial"
    assert "80%" in capped["warnings"][0]


def test_five_percent_threshold_is_inclusive(data):
    """A contributor exactly at 5% is eligible; a smaller contributor stays untouched."""
    source = {"name": "Threshold", "ingredients": [
        {"name": "vegetable_oil", "grams": 5}, {"name": "olive_oil", "grams": 4},
        {"name": "palm_oil", "grams": 91},
    ], "core_ingredients": ["palm_oil"]}
    result = run(source, [edit("nutrient", "fat_g", 4)], data)
    assert result["recipe"]["ingredients"] == {"vegetable_oil": 1, "olive_oil": 4, "palm_oil": 91}
    assert result["modification_results"][0]["status"] == "met"


def test_finalize_rechecks_amounts_after_later_changes(data):
    """Outcome calculations accept a later recipe so compensation cannot hide regained nutrients."""
    recipe = resolve_recipe("lemonade", data)
    result = apply_modifications(recipe, [edit("nutrient", "sugar_g", 30)], data)
    after_repair = deepcopy(result["recipe"])
    after_repair["ingredients"]["honey"] = 2
    rows = finalize_modification_results(recipe, after_repair, result["modifications"],
                                         result["modification_results"], data)
    final_sugar = totals(after_repair["ingredients"], data)["nutrients"]["sugar_g"]
    assert rows[0]["new_amount"] == final_sugar
    assert rows[0]["achieved_percent"] == pytest.approx((52.5 - final_sugar) / 52.5 * 100)
    assert rows[0]["status"] == "partial"


def test_explicit_unknown_edit_and_maximum_ingredient_cut(data):
    """Users can remove their unknown foods and request the full 99% ingredient reduction."""
    source = {"name": "Custom", "ingredients": [
        {"name": "sugra", "grams": 10}, {"name": "sugar", "grams": 100},
    ]}
    result = run(source, [edit("ingredient", "sugra", action="remove"), edit("ingredient", "sugar", 99)], data)
    assert result["recipe"]["ingredients"] == {"sugar": 1}
    assert result["touched_ingredients"] == ["sugra", "sugar"]


def test_determinism_and_no_input_or_result_aliasing(data):
    """Repeated calls agree, and even editing a returned recipe cannot mutate caller data."""
    source = {"name": "Custom", "tags": ["beverage"], "ingredients": [
        {"name": "white_sugar", "grams": 20}, {"name": "water", "grams": 100},
    ]}
    requests = [edit("ingredient", "sugar", 40)]
    original_data, original_source, original_requests = deepcopy((data, source, requests))
    first = analyze(source, data)
    assert first == analyze(source, data)
    baseline = deepcopy(first["recipe"])
    cut = apply_modifications(first["recipe"], requests, data)
    assert cut == apply_modifications(first["recipe"], requests, data)
    assert first["recipe"] == baseline
    json.dumps(cut, allow_nan=False)
    cut["recipe"]["tags"].append("changed")
    first["recipe"]["ingredients"]["sugar"] = 999
    assert data == original_data
    assert source == original_source
    assert requests == original_requests


def test_empty_modifications_leave_a_copy_of_the_recipe(data):
    """An empty edit list is a valid baseline and does not invent cuts or warnings."""
    recipe = resolve_recipe("lemonade", data)
    result = apply_modifications(recipe, None, data)
    assert result["recipe"] == recipe
    assert result["recipe"] is not recipe
    assert result["modification_results"] == []
    assert result["warning_details"] == []
