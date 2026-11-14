"""Phase 4 response checks, staged separately until the Phase 3 test boundary passes."""

from copy import deepcopy
import json
import time

import pytest

from catalog import load_data, resolve_recipe
from compare import build_response, comparison_rows, data_quality
from metrics import totals
from modify import apply_modifications
from taste import repair
from engine import reformulate


@pytest.fixture(scope="module")
def data():
    """Use the local fixture catalog to make the response contract reproducible offline."""
    return load_data()


def run_output(source, edits, data, options=None, **legacy):
    """Run the pure pipeline so output assertions also cover real repair integration."""
    original = resolve_recipe(source, data)
    options = {"max_compensators": 3, "exclude_compensators": [],
               "servings": original["servings"], "include_trace": True, **(options or {})}
    cuts = apply_modifications(original, edits, data)
    repaired = repair(original, cuts, options, data)
    return build_response(original, cuts, repaired, options, data, **legacy)


def edit(kind, target, percent=30, action="reduce"):
    """Keep common edit requests concise so tests emphasize the output being checked."""
    return {"type": kind, "target": target, "percent": percent, "action": action}


def test_full_contract_and_legacy_keys(data):
    """Existing clients retain every field while v2 adds complete presentation data."""
    result = run_output("lemonade", [edit("ingredient", "sugar")], data,
                        goal="sugar", reduce_percent=30)
    assert {"dish", "goal", "reduce_percent", "original_recipe", "new_recipe",
            "added_compensators", "scores", "new_flavor_notes", "nutrition", "warnings",
            "trace", "data_source", "schema_version", "servings", "recipe_name",
            "modification_results", "ingredient_changes", "nutrient_comparison",
            "chemical_comparison", "taste_profile", "lost_flavor_notes", "headline",
            "warning_details", "badges", "trace_detail", "data_quality", "options_used"} <= result.keys()
    assert result["goal"] == "sugar"
    assert result["reduce_percent"] == 30
    assert result["schema_version"] == 2
    assert {"sugar_saved_g", "sodium_saved_mg", "fat_saved_g"} <= result["nutrition"].keys()
    assert {"taste_retention_pct", "flavor_preserved_pct", "target_reached", "by_axis"} <= result["scores"].keys()
    assert result["warnings"] == [row["message"] for row in result["warning_details"]]
    assert result["trace"] == [row["text"] for row in result["trace_detail"]]
    json.dumps(result, allow_nan=False)


def test_v2_goal_null_and_servings_override(data):
    """V2 requests expose null legacy goals and consistently use the overridden portions."""
    result = run_output("lemonade", [edit("nutrient", "sugar_g")], data, {"servings": 3})
    assert result["goal"] is None
    assert result["reduce_percent"] is None
    assert result["servings"] == result["options_used"]["servings"] == 3
    sugar = next(row for row in result["nutrient_comparison"] if row["id"] == "sugar_g")
    assert sugar["original_per_serving"] == round(sugar["original_total"] / 3, 2)
    assert sugar["new_per_serving"] == pytest.approx(sugar["new_total"] / 3, abs=0.01)
    assert sugar["targeted"] is True


def test_modification_outcome_uses_final_recipe(data):
    """Compensator nutrients count in achieved reduction instead of reporting the pre-repair cut."""
    result = run_output("butter_chicken", [edit("nutrient", "fat_g", 30)], data)
    metric = next(row for row in result["nutrient_comparison"] if row["id"] == "fat_g")
    outcome = result["modification_results"][0]
    assert outcome["new_amount"] == metric["new_total"]
    assert outcome["achieved_percent"] == -metric["delta_pct"]
    assert result["nutrition"]["fat_saved_g"] == -metric["delta_total"]


def test_ingredient_changes_order_reasons_and_remove(data):
    """The UI can draw all ingredient rows in source order and explain explicit removals."""
    original = resolve_recipe("lemonade", data)
    result = run_output("lemonade", [edit("ingredient", "sugar", action="remove")], data)
    rows = result["ingredient_changes"]
    assert [row["ingredient"] for row in rows[:len(original["ingredients"])]] == list(original["ingredients"])
    removed = next(row for row in rows if row["ingredient"] == "sugar")
    assert removed["status"] == "removed"
    assert removed["new_g"] == 0
    assert removed["delta_pct"] == -100
    assert removed["modification_ids"] == ["m1"]
    assert "asked to remove" in removed["reason"]
    for row in rows:
        if row["status"] == "added":
            assert row["original_g"] == 0
            assert row["delta_pct"] is None
            assert row["is_compensator"] is True
            assert "restore" in row["reason"]
    assert result["modification_results"][0]["requested_percent"] is None


def test_compensators_have_explanations_and_alternatives(data):
    """Every chosen compensator exposes both the old score fields and the new rationale."""
    result = run_output("lemonade", [edit("ingredient", "sugar")], data)
    assert result["added_compensators"]
    required = {"ingredient", "grams", "taste_boost", "molecule_overlap", "score",
                "display_name", "axis", "axis_gains", "mechanism", "reason", "alternatives"}
    for row in result["added_compensators"]:
        assert required <= row.keys()
        assert row["reason"]
        assert len(row["alternatives"]) <= 3
        for alternative in row["alternatives"]:
            assert {"ingredient", "display_name", "score", "grams_needed", "reason_not_chosen"} <= alternative.keys()


def test_comparison_delta_sorting_daily_values_and_direction(data):
    """Comparisons use signed changes, preserve contributor order, and respect beneficial metrics."""
    result = run_output("tomato_soup", [edit("ingredient", "tomato", 30)], data,
                        {"max_compensators": 0})
    fiber = next(row for row in result["nutrient_comparison"] if row["id"] == "fiber_g")
    assert fiber["direction"] == "higher_is_better"
    assert fiber["change_type"] == "worsened"
    assert fiber["delta_total"] < 0
    assert fiber["new_dv_pct"] <= fiber["original_dv_pct"]
    for row in result["nutrient_comparison"] + result["chemical_comparison"]:
        amounts = [item["original_amount"] for item in row["by_ingredient"]]
        assert amounts == sorted(amounts, reverse=True)
        assert row["delta_total"] == pytest.approx(row["new_total"] - row["original_total"], abs=0.011)
        assert all(item["original_amount"] > 0 or item["new_amount"] > 0
                   for item in row["by_ingredient"])


def test_zero_baselines_are_null_and_no_daily_reference_stays_null(data):
    """New metrics avoid division by zero and chemicals without a reference never invent one."""
    original = resolve_recipe({"name": "Water", "ingredients": [{"name": "water", "grams": 100}]}, data)
    changed = deepcopy(original)
    changed["ingredients"]["sugar"] = 5
    rows = comparison_rows(original, changed, [], 1, data)
    sugar = next(row for row in rows["nutrient_comparison"] if row["id"] == "sugar_g")
    assert sugar["delta_pct"] is None
    assert sugar["change_type"] == "worsened"
    result = run_output("instant_noodles", [edit("chemical", "msg_g", 20)], data)
    msg = next(row for row in result["chemical_comparison"] if row["id"] == "msg_g")
    assert msg["original_dv_pct"] is None
    assert msg["new_dv_pct"] is None


def test_half_percent_tolerance_uses_raw_math(data):
    """Sub-threshold changes remain unchanged even when display rounding hides their exact size."""
    original = resolve_recipe({"name": "Sugar", "ingredients": [{"name": "sugar", "grams": 100}]}, data)
    changed = deepcopy(original)
    changed["ingredients"]["sugar"] = 99.6
    rows = comparison_rows(original, changed, [], 1, data)
    assert all(row["change_type"] == "unchanged" for row in rows["nutrient_comparison"])
    changed["ingredients"]["sugar"] = 99.4
    rows = comparison_rows(original, changed, [], 1, data)
    assert all(row["change_type"] == "improved" for row in rows["nutrient_comparison"])


def test_headline_prioritizes_targets_and_caps_four(data):
    """Requested metrics lead the short headline, followed by the largest other changes."""
    result = run_output("chocolate_cake", [edit("nutrient", "sugar_g", 20),
                                          edit("nutrient", "fat_g", 20)], data)
    chosen = result["headline"]["key_metrics"]
    assert 1 <= len(chosen) <= 4
    targeted_ids = {row["id"] for row in result["nutrient_comparison"]
                    if row["targeted"] and row["change_type"] != "unchanged"}
    assert {row["id"] for row in chosen[:len(targeted_ids)]} == targeted_ids
    assert "Taste retention" in result["headline"]["summary_text"]
    assert "compensator" in result["headline"]["summary_text"]


def test_trace_order_and_disabled_trace(data):
    """Trace text mirrors structured entries and can be disabled without losing either key."""
    source = "lemonade"
    edits = [edit("ingredient", "sugar")]
    result = run_output(source, edits, data)
    phases = [row["phase"] for row in result["trace_detail"]]
    order = {phase: index for index, phase in enumerate(("baseline", "modify", "deficit", "compensate", "score"))}
    assert phases[0] == "baseline"
    assert phases[-1] == "score"
    assert [order[phase] for phase in phases] == sorted(order[phase] for phase in phases)
    quiet = run_output(source, edits, data, {"include_trace": False})
    assert quiet["trace"] == quiet["trace_detail"] == []


def test_unknown_and_mixed_source_provenance_stays_honest(data):
    """Using one sourced ingredient never turns remaining placeholder estimates into real values."""
    imported = deepcopy(data)
    imported["meta"]["data_source"] = "recipedb+flavordb"
    imported["ingredients"]["sugar"]["data_quality"] = "sourced"
    imported["ingredients"]["sugar"]["source_notes"] = ["Imported nutrient values; taste remains an estimate."]
    source = {"name": "Mixed drink", "ingredients": [
        {"name": "sugar", "grams": 20}, {"name": "water", "grams": 100},
        {"name": "unknown leaf", "grams": 3},
    ]}
    result = run_output(source, [edit("ingredient", "sugar", 20)], imported,
                        {"max_compensators": 0})
    quality = result["data_quality"]
    assert quality["data_source"] == "recipedb+flavordb"
    assert quality["placeholder_values"] is True
    assert quality["unknown_ingredients"][0]["name"] == "unknown leaf"
    assert "Imported nutrient values; taste remains an estimate." in quality["notes"]
    assert quality["ingredient_provenance"]["sugar"]["data_quality"] == "sourced"
    assert any(row["code"] == "UNKNOWN_INGREDIENT" for row in result["warning_details"])


def test_unused_placeholders_do_not_taint_used_sourced_rows(data):
    """Provenance is derived from used ingredients, including field-level quality markers."""
    imported = deepcopy(data)
    imported["meta"] = {"data_source": "recipedb+flavordb", "notes": ["Taste predictions are estimates."]}
    imported["ingredients"]["water"]["data_quality"] = {"nutrients": "sourced", "taste": "estimated"}
    original = resolve_recipe({"name": "Water", "ingredients": [{"name": "water", "grams": 100}]}, imported)
    quality = data_quality(original, original, imported)
    assert quality["placeholder_values"] is False
    imported["ingredients"]["water"]["data_quality"]["taste"] = "placeholder_approx"
    assert data_quality(original, original, imported)["placeholder_values"] is True


def test_response_is_deterministic_and_does_not_mutate_inputs(data):
    """Rounding and decoration copy pipeline objects, so repeated calls remain identical."""
    original = resolve_recipe("tomato_soup", data)
    cuts = apply_modifications(original, [edit("chemical", "sodium_mg", 30)], data)
    options = {"max_compensators": 3, "exclude_compensators": [], "include_trace": True, "servings": 2}
    repaired = repair(original, cuts, options, data)
    before = deepcopy((original, cuts, repaired, options, data))
    first = build_response(original, cuts, repaired, options, data)
    second = build_response(original, cuts, repaired, options, data)
    assert first == second
    assert (original, cuts, repaired, options, data) == before


@pytest.mark.parametrize("dish", ["lemonade", "tomato_soup", "butter_chicken", "chicken_curry",
                                  "chocolate_cake", "caesar_dressing", "instant_noodles", "ham_cheese_sandwich"])
def test_catalog_output_invariant_sweep(dish, data):
    """Every catalog recipe yields finite complete comparisons under an energy reduction."""
    result = run_output(dish, [edit("nutrient", "calories_kcal", 20)], data)
    json.dumps(result, allow_nan=False)
    original = totals(resolve_recipe(dish, data)["ingredients"], data)
    final = totals(result["new_recipe"]["ingredients"], data)
    for key, group in (("nutrient_comparison", "nutrients"), ("chemical_comparison", "chemicals")):
        for row in result[key]:
            assert row["original_total"] == round(original[group][row["id"]], 2)
            assert row["new_total"] == round(final[group][row["id"]], 2)
            assert row["delta_per_serving"] == pytest.approx(row["delta_total"] / result["servings"], abs=0.011)
    assert result["scores"]["taste_retention_pct"] <= 100
    assert result["trace"] == [row["text"] for row in result["trace_detail"]]


def test_full_metric_and_stacked_sweep_under_five_seconds(data):
    """Exercise every present metric at four cuts plus stacked edits through the public facade."""
    snapshot = deepcopy(data)
    start = time.perf_counter()
    requests = []
    for dish in data["dishes"]:
        baseline = totals(data["dishes"][dish]["ingredients"], data)
        present = [(kind, target) for kind, group in (("nutrient", "nutrients"), ("chemical", "chemicals"))
                   for target, amount in baseline[group].items() if amount > 0]
        requests.extend((dish, [edit(kind, target, percent)]) for kind, target in present for percent in (10, 30, 50, 80))
        requests.append((dish, [edit(kind, target, 30) for kind, target in present[:3]]))
    for dish, edits in requests:
        result = reformulate(dish, edits, data=data)
        json.dumps(result, allow_nan=False)
        assert result["trace"] == [row["text"] for row in result["trace_detail"]]
        assert [row["id"] for row in result["modification_results"]] == [f"m{index + 1}" for index in range(len(edits))]
        for row in result["nutrient_comparison"] + result["chemical_comparison"]:
            assert row["new_total"] - row["original_total"] == pytest.approx(row["delta_total"], abs=0.010001)
            assert row["new_total"] / result["servings"] == pytest.approx(row["new_per_serving"], abs=0.010001)
            if row["original_total"] == 0:
                assert row["delta_pct"] is None
        for row in result["ingredient_changes"]:
            expected = "added" if row["original_g"] == 0 else "removed" if row["new_g"] == 0 else "reduced" if row["new_g"] < row["original_g"] else "unchanged"
            assert row["status"] == expected
    assert data == snapshot
    assert time.perf_counter() - start < 5
