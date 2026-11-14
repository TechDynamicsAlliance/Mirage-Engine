"""Unit conversions preserve explicit assumptions rather than guessing every density."""
import pytest
from catalog import MirageError, load_data
from units import to_grams, parse_ingredient_lines


@pytest.mark.parametrize("quantity,unit,expected", [(1,"kg",1000),(2,"mg",.002),("1/2","g",.5),("1 1/2","g",1.5), (1,"lb",453.59237)])
def test_mass_and_fractions(quantity, unit, expected):
    """Metric units and the customary units found in RecipeDB convert without food assumptions."""
    assert to_grams(quantity, unit) == pytest.approx(expected)


def test_volume_and_piece_weights():
    """Liquid default density and declared solid portion weights follow different paths."""
    assert to_grams(2, "tbsp", {"grams_per_cup": 240}) == 30
    assert to_grams(2, "piece", {"grams_per_piece": 50}) == 100
    assert to_grams(1, "l", {"role": "liquid"}) == 1000
    with pytest.raises(MirageError):
        to_grams(1, "cup", {})


def test_parser_reports_unknown_and_unparsed_lines():
    """A failed line is visible instead of being silently dropped or assigned a made-up mass."""
    data = load_data()
    data["ingredients"]["butter"]["grams_per_cup"] = 227
    data["ingredients"]["sugar"]["grams_per_cup"] = 200
    result = parse_ingredient_lines("2 tbsp butter\n1/2 cup sugar\n3 g sugarr\nsalt to taste", data=data)
    assert result["custom_recipe"]["ingredients"][0]["grams"] == pytest.approx(28.375)
    assert result["custom_recipe"]["ingredients"][1]["grams"] == 100
    assert len(result["unparsed_lines"]) == 1
    assert result["unresolved_ingredients"][0]["name"] == "sugarr"
