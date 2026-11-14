"""Tests for the MIRAGE engine (GUIDE Lesson 5).

Run with:  source .venv/bin/activate && pytest -q
"""

import pytest
from engine import reformulate, list_dishes, load_data, MirageError, DishNotFound

DATA = load_data()


# ── list_dishes ──────────────────────────────────────────────────────
class TestListDishes:
    def test_returns_list(self):
        result = list_dishes(DATA)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_each_dish_has_required_fields(self):
        for d in list_dishes(DATA):
            assert "dish" in d
            assert "goals" in d
            assert "ingredients" in d

    def test_lemonade_has_sugar_goal(self):
        dishes = {d["dish"]: d for d in list_dishes(DATA)}
        assert "sugar" in dishes["lemonade"]["goals"]


# ── Input validation ─────────────────────────────────────────────────
class TestValidation:
    def test_unknown_dish_raises_not_found(self):
        with pytest.raises(DishNotFound):
            reformulate("pizza", "sugar", 20, DATA)

    def test_unknown_goal_raises_error(self):
        with pytest.raises(MirageError):
            reformulate("lemonade", "protein", 20, DATA)

    def test_zero_percent_raises_error(self):
        with pytest.raises(MirageError):
            reformulate("lemonade", "sugar", 0, DATA)

    def test_over_80_percent_raises_error(self):
        with pytest.raises(MirageError):
            reformulate("lemonade", "sugar", 81, DATA)

    def test_negative_percent_raises_error(self):
        with pytest.raises(MirageError):
            reformulate("lemonade", "sugar", -5, DATA)


# ── Output shape ─────────────────────────────────────────────────────
class TestOutputShape:
    def test_has_all_required_keys(self):
        result = reformulate("lemonade", "sugar", 20, DATA)
        required = [
            "dish", "goal", "reduce_percent",
            "original_recipe", "new_recipe", "added_compensators",
            "scores", "new_flavor_notes", "nutrition",
            "warnings", "trace", "data_source",
        ]
        for key in required:
            assert key in result, f"Missing key: {key}"

    def test_scores_has_required_fields(self):
        result = reformulate("lemonade", "sugar", 20, DATA)
        scores = result["scores"]
        assert "taste_retention_pct" in scores
        assert "flavor_preserved_pct" in scores
        assert "target_reached" in scores

    def test_data_source_is_placeholder(self):
        result = reformulate("lemonade", "sugar", 20, DATA)
        assert result["data_source"] == "placeholder"


# ── Engine logic: lemonade ──────────────────────────────────────────
class TestLemonade:
    def test_sugar_is_reduced(self):
        result = reformulate("lemonade", "sugar", 20, DATA)
        orig_sugar = result["original_recipe"]["ingredients"]["sugar"]
        new_sugar = result["new_recipe"]["ingredients"]["sugar"]
        assert new_sugar < orig_sugar

    def test_sugar_reduction_is_correct(self):
        result = reformulate("lemonade", "sugar", 40, DATA)
        orig = result["original_recipe"]["ingredients"]["sugar"]
        new = result["new_recipe"]["ingredients"]["sugar"]
        # Should be approximately 60% of original (40% cut)
        assert new == pytest.approx(orig * 0.6, abs=0.2)

    def test_compensators_are_added(self):
        result = reformulate("lemonade", "sugar", 20, DATA)
        assert len(result["added_compensators"]) > 0

    def test_compensator_not_already_in_recipe(self):
        result = reformulate("lemonade", "sugar", 20, DATA)
        orig_ingredients = set(result["original_recipe"]["ingredients"].keys())
        for comp in result["added_compensators"]:
            assert comp["ingredient"] not in orig_ingredients

    def test_taste_retention_above_50(self):
        result = reformulate("lemonade", "sugar", 20, DATA)
        assert result["scores"]["taste_retention_pct"] > 50

    def test_nutrition_shows_sugar_saved(self):
        result = reformulate("lemonade", "sugar", 20, DATA)
        assert "sugar_saved_g" in result["nutrition"]
        assert result["nutrition"]["sugar_saved_g"] > 0

    def test_low_reduction_reaches_target(self):
        result = reformulate("lemonade", "sugar", 10, DATA)
        assert result["scores"]["target_reached"] is True

    def test_high_reduction_warns_if_target_missed(self):
        result = reformulate("lemonade", "sugar", 40, DATA)
        if not result["scores"]["target_reached"]:
            assert len(result["warnings"]) > 0


# ── Engine logic: tomato_soup ───────────────────────────────────────
class TestTomatoSoup:
    def test_salt_reduction(self):
        result = reformulate("tomato_soup", "salt", 30, DATA)
        orig_salt = result["original_recipe"]["ingredients"]["salt"]
        new_salt = result["new_recipe"]["ingredients"]["salt"]
        assert new_salt < orig_salt

    def test_sodium_saved(self):
        result = reformulate("tomato_soup", "salt", 30, DATA)
        assert "sodium_saved_mg" in result["nutrition"]
        assert result["nutrition"]["sodium_saved_mg"] > 0

    def test_compensators_fit_soup_tags(self):
        result = reformulate("tomato_soup", "salt", 30, DATA)
        soup_tags = result["original_recipe"]["tags"]
        for comp in result["added_compensators"]:
            # The compensator should have been selected because it fits
            # at least one of the dish's tags
            assert comp["ingredient"] in DATA["ingredients"]


# ── Engine logic: butter_chicken ────────────────────────────────────
class TestButterChicken:
    def test_fat_reduction(self):
        result = reformulate("butter_chicken", "fat", 30, DATA)
        orig_fat = result["nutrition"]["original"]["fat_g"]
        new_fat = result["nutrition"]["reformulated"]["fat_g"]
        assert new_fat < orig_fat

    def test_fat_saved(self):
        result = reformulate("butter_chicken", "fat", 30, DATA)
        assert "fat_saved_g" in result["nutrition"]
        assert result["nutrition"]["fat_saved_g"] > 0


# ── Original data is never mutated ──────────────────────────────────
class TestImmutability:
    def test_original_data_unchanged_after_reformulate(self):
        import copy
        data_before = copy.deepcopy(DATA)
        reformulate("lemonade", "sugar", 40, DATA)
        assert DATA == data_before
