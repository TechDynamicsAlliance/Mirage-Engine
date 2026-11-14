"""Adapter tests use a clearly made-up payload, not a claim about actual upstream recipes."""
from copy import deepcopy
from catalog import load_data
from recipe_adapter import recipedb_to_recipe


def test_made_up_payload_is_pure_and_recovers_fraction_unit_from_phrase():
    """Original ingredient text can safely recover a malformed structured unit."""
    data = load_data()
    data["ingredients"]["sugar"]["grams_per_cup"] = 200
    payload = {"recipe": {"Recipe_id": "999", "Recipe_title": "Made-up test", "servings": "2"}, "ingredients": [
        {"ingredient": "sugar", "quantity": "1 1/2", "unit": "1/2", "ingredient_Phrase": "1 1/2 cups sugar"},
        {"ingredient": "water", "quantity": "100", "unit": "ml"},
        {"ingredient": "unknown", "quantity": "some", "unit": ""},
    ]}
    before = deepcopy((payload, data))
    recipe = recipedb_to_recipe({"success": True, "data": payload}, data)
    assert recipe.ingredients == [{"name": "sugar", "grams": 300}, {"name": "water", "grams": 100}]
    assert recipe.servings == 2
    assert len(recipe.unresolved_quantities) == 1
    assert (payload, data) == before


def test_documented_wrapper_and_unknown_yield():
    """Non-numeric yields become an explicitly labelled whole recipe, never an invented serving count."""
    payload = {"payload": {"data": {"Recipe_id": "1", "Recipe_title": "Made-up", "servings": "2 quarts"},
                           "ingredients": [{"ingredient": "water", "quantity": "50", "unit": "g"}]}}
    recipe = recipedb_to_recipe(payload, load_data())
    assert recipe.servings == 1
    assert recipe.source_metadata["notes"]
