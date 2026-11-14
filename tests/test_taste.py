"""Phase 3 checks for multi-axis repair and aggregate, rounding-safe limits."""

from copy import deepcopy
import json

import pytest

from catalog import load_data, resolve_recipe
from metrics import totals
from modify import apply_modifications
from taste import repair


@pytest.fixture
def data():
    """Provide an isolated catalog so altered candidate fixtures cannot leak between tests."""
    return load_data()


def run(data, source="lemonade", target="sugar", percent=60, kind="ingredient", options=None):
    """Run only resolution, cutting and repair to test Phase 3 independently of the old engine."""
    original = resolve_recipe(source, data)
    cut = apply_modifications(original, [{"type": kind, "target": target, "action": "reduce", "percent": percent}], data)
    return original, cut, repair(original, cut, options or {}, data)


def synthetic(data, candidates, *, base_taste=None, base_grams=100, water_grams=0):
    """Make explicitly artificial exact-value recipes that isolate caps and score arithmetic."""
    data = deepcopy(data)
    data["ingredients"] = {
        "base": {"display_name": "Base", "aliases": [], "role": "sweetener",
                 "nutrients_per_g": {"sugar_g": 1}, "chemicals_per_g": {"sodium_mg": 1},
                 "taste_per_g": base_taste or {"sweet": 1}, "molecules": ["shared", "lost"]},
        "water": {"display_name": "Water", "aliases": [], "role": "liquid", "molecules": []},
    }
    for name, overrides in candidates.items():
        info = {"display_name": name.title(), "aliases": [], "role": "condiment",
                "nutrients_per_g": {}, "chemicals_per_g": {}, "molecules": ["shared", "new"],
                "taste_per_g": {"sweet": 1},
                "compensator": {"compensates": ["sweet"], "fits": ["test"], "max_g": 100,
                                "mechanism": "moisture_body"}}
        for key, value in overrides.items():
            if key == "compensator":
                info[key].update(value)
            else:
                info[key] = value
        data["ingredients"][name] = info
    rows = [{"name": "base", "grams": base_grams}]
    if water_grams:
        rows.append({"name": "water", "grams": water_grams})
    source = {"name": "Artificial test recipe", "tags": ["test"], "ingredients": rows,
              "core_ingredients": []}
    return data, source


def test_fat_repair_has_additions_and_numeric_scores(data):
    """Fat reduction must repair richness and produce real scores instead of legacy nulls."""
    _, _, result = run(data, "butter_chicken", "fat_g", 30, "nutrient")
    assert result["added_compensators"]
    assert "richness" in result["affected_axes"]
    assert isinstance(result["scores"]["taste_retention_pct"], float)
    assert isinstance(result["scores"]["target_reached"], bool)


def test_weak_lemon_zest_is_skipped_with_trace(data):
    """A 60% sugar cut must not trigger a tiny ineffective lemon-zest addition."""
    _, _, result = run(data)
    assert "lemon_zest" not in [row["ingredient"] for row in result["added_compensators"]]
    assert any("Skipped lemon_zest" in row["text"] and "1 percentage point" in row["text"]
               for row in result["trace_detail"])


@pytest.mark.parametrize("maximum", [0, 1, 2, 3, 5])
def test_addition_count_obeys_options(data, maximum):
    """Every accepted compensator limit, including disabled repair, must be respected."""
    _, cut, result = run(data, options={"max_compensators": maximum})
    assert len(result["added_compensators"]) <= maximum
    if maximum == 0:
        assert result["recipe"] == cut["recipe"]
        assert result["limit_reached"]


def test_excluded_candidates_and_aliases_are_honored(data):
    """Excluding a name or its catalog alias must prevent that compensator from being added."""
    _, _, result = run(data, options={"exclude_compensators": ["vanilla", "mint"]})
    assert result["added_compensators"] == []


@pytest.mark.parametrize("action", ["remove", "reduce"])
def test_touched_ingredients_never_return_or_change_again(data, action):
    """A strong existing compensator is locked when the user explicitly reduces or removes it."""
    original = resolve_recipe({"name": "Vanilla drink", "tags": ["beverage"], "ingredients": [
        {"name": "vanilla_extract", "grams": 3}, {"name": "sugar", "grams": 50},
        {"name": "water", "grams": 500}]}, data)
    modifications = [{"type": "ingredient", "target": "vanilla_extract", "action": action, "percent": 60},
                     {"type": "ingredient", "target": "sugar", "action": "reduce", "percent": 60}]
    cut = apply_modifications(original, modifications, data)
    result = repair(original, cut, {}, data)
    assert "vanilla_extract" not in [row["ingredient"] for row in result["added_compensators"]]
    assert result["recipe"]["ingredients"].get("vanilla_extract") == cut["recipe"]["ingredients"].get("vanilla_extract")


def test_safe_cap_is_enforced_after_rounding_up(data):
    """A fractional safe cap must round downward even though desired dosing rounds upward."""
    data, source = synthetic(data, {"candidate": {"compensator": {"max_g": 1.25}}})
    _, _, result = run(data, source, "base", 50)
    assert result["added_compensators"][0]["grams"] == 1.2
    assert result["limit_reached"]


def test_total_compensator_mass_stays_within_original_tenth(data):
    """Separate safe additions must share a single 10% original-mass budget."""
    data, source = synthetic(data, {
        "first": {"compensator": {"max_g": 6}}, "second": {}, "third": {}})
    _, _, result = run(data, source, "base", 50)
    assert [row["grams"] for row in result["added_compensators"]] == [6, 4]
    assert sum(row["grams"] for row in result["added_compensators"]) <= 10


@pytest.mark.parametrize("kind,metric,content,group", [
    ("nutrient", "sugar_g", "nutrients_per_g", "nutrients"),
    ("chemical", "sodium_mg", "chemicals_per_g", "chemicals"),
])
def test_giveback_is_an_aggregate_budget_with_rounding(data, kind, metric, content, group):
    """Multiple compensators together may give back only a quarter of pre-repair savings."""
    data, source = synthetic(data, {
        "first": {content: {metric: 2}, "compensator": {"max_g": 2}},
        "second": {content: {metric: 2}}, "third": {content: {metric: 2}},
    }, water_grams=1000)
    original, cut, result = run(data, source, metric, 50, kind)
    initial = totals(original["ingredients"], data)[group][metric]
    after_cut = totals(cut["recipe"]["ingredients"], data)[group][metric]
    final = totals(result["recipe"]["ingredients"], data)[group][metric]
    assert [row["grams"] for row in result["added_compensators"]] == [2, 4.2]
    assert final - after_cut <= 0.25 * (initial - after_cut)
    assert result["limit_reached"]


def test_no_savings_means_no_giveback(data):
    """An impossible metric cut grants no budget for compensation that worsens that metric."""
    data, source = synthetic(data, {"candidate": {"nutrients_per_g": {"sugar_g": 1}}})
    original = resolve_recipe(source, data)
    cut = {"recipe": deepcopy(original), "touched_ingredients": [],
           "modifications": [{"type": "nutrient", "target": "sugar_g"}]}
    cut["recipe"]["ingredients"]["base"] = 50
    # Keep sugar unchanged while removing taste: this isolates zero savings.
    data["ingredients"]["sugar_only"] = {"nutrients_per_g": {"sugar_g": 1}, "taste_per_g": {}}
    cut["recipe"]["ingredients"]["sugar_only"] = 50
    result = repair(original, cut, {}, data)
    assert result["added_compensators"] == []


def test_weighted_ranking_credits_every_axis_and_reweights(data):
    """One addition's cross-axis gains must affect the next choice and final weakest-axis score."""
    data, source = synthetic(data, {
        "dual": {"taste_per_g": {"sweet": 1, "richness": 2},
                 "compensator": {"compensates": ["sweet", "richness"]}},
        "sweet_only": {"taste_per_g": {"sweet": 2}, "molecules": []},
    }, base_taste={"sweet": 1, "richness": 1}, water_grams=1000)
    _, _, result = run(data, source, "base", 50)
    first, second = result["added_compensators"]
    assert first["ingredient"] == "dual"
    assert first["score"] == 2.25  # (0.5*1 + 0.5*2) * (1 + 1/2)
    assert first["axis"] == "richness"
    assert first["axis_gains"] == {"sweet": 22.5, "richness": 45}
    assert second["ingredient"] == "sweet_only"
    assert result["final"]["sweet"] >= 95
    assert result["final"]["richness"] == 95
    assert result["scores"]["taste_retention_pct"] == 95
    assert result["scores"]["target_reached"]


def test_alternatives_are_useful_valid_and_limited_to_three(data):
    """Explanations must list only feasible useful candidates, never excluded or weak fillers."""
    data, source = synthetic(data, {**{f"candidate_{n}": {} for n in range(6)},
                                    "weak": {"taste_per_g": {"sweet": 0.0001}}}, water_grams=1000)
    _, _, result = run(data, source, "base", 50,
                      options={"exclude_compensators": ["candidate_1"], "max_compensators": 1})
    entry = result["added_compensators"][0]
    assert [row["ingredient"] for row in entry["alternatives"]] == ["candidate_2", "candidate_3", "candidate_4"]
    assert all(row["grams_needed"] == 45 for row in entry["alternatives"])
    assert all(row["reason_not_chosen"] for row in entry["alternatives"])


def test_zero_axis_and_unaffected_recipe_score_cleanly(data):
    """No deficit or original taste must produce finite full retention without additions."""
    original = resolve_recipe({"name": "Water", "ingredients": [{"name": "water", "grams": 100}]}, data)
    cut = apply_modifications(original, [], data)
    result = repair(original, cut, {}, data)
    assert result["scores"] == {"taste_retention_pct": 100.0, "flavor_preserved_pct": 100.0,
                                "target_reached": True, "by_axis": {axis: 100.0 for axis in data["taste_axes"]}}
    assert result["affected_axes"] == []
    assert result["added_compensators"] == []
    json.dumps(result, allow_nan=False)


def test_flavor_fingerprint_counts_lost_and_new_molecules(data):
    """Removing a food and adding another must expose both lost and newly introduced molecules."""
    data, source = synthetic(data, {"candidate": {}}, water_grams=1000)
    original = resolve_recipe(source, data)
    cut = apply_modifications(original, [{"type": "ingredient", "target": "base", "action": "remove"}], data)
    result = repair(original, cut, {}, data)
    assert result["lost_flavor_notes"] == ["lost"]
    assert result["new_flavor_notes"] == ["new"]
    assert result["scores"]["flavor_preserved_pct"] == 50


def test_repair_is_deterministic_and_does_not_mutate_any_input(data):
    """Shared input objects and catalog data must remain independent from returned state."""
    original, cut, _ = run(data)
    options = {"max_compensators": 3, "exclude_compensators": ["vanilla"]}
    snapshot = deepcopy((original, cut, options, data))
    first = repair(original, cut, options, data)
    assert first == repair(original, cut, options, data)
    first["recipe"]["tags"].append("changed")
    assert (original, cut, options, data) == snapshot
    json.dumps(first, allow_nan=False)


def test_every_catalog_candidate_respects_safe_caps(data):
    """Representative nutrient and sodium cuts must never emit a dose above its configured cap."""
    for dish in data["dishes"]:
        for kind, target in [("nutrient", "fat_g"), ("chemical", "sodium_mg")]:
            original = resolve_recipe(dish, data)
            group = "nutrients" if kind == "nutrient" else "chemicals"
            if totals(original["ingredients"], data)[group][target] <= 0:
                continue
            _, _, result = run(data, dish, target, 80, kind)
            for row in result["added_compensators"]:
                assert row["grams"] <= data["ingredients"][row["ingredient"]]["compensator"]["max_g"]
            assert sum(row["grams"] for row in result["added_compensators"]) <= sum(original["ingredients"].values()) * 0.1
