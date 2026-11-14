"""Generate reproducible frontend examples using the real engine and labelled demo fixtures."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import analyze, reformulate, list_dishes, load_data, MirageError


def main():
    """Write actual engine outputs so examples cannot drift from the implemented response contract."""
    data = load_data()
    folder = Path(__file__).resolve().parents[1] / "examples"
    folder.mkdir(exist_ok=True)
    outputs = {"dishes": list_dishes(data), "dish_detail_butter_chicken": analyze("butter_chicken", data)}
    edits = {
        "ingredient_butter": [{"type": "ingredient", "target": "butter", "action": "reduce", "percent": 30}],
        "nutrient_calories": [{"type": "nutrient", "target": "calories_kcal", "action": "reduce", "percent": 20}],
        "chemical_sodium": [{"type": "chemical", "target": "sodium_mg", "action": "reduce", "percent": 30}],
        "remove_ingredient": [{"type": "ingredient", "target": "butter", "action": "remove"}],
    }
    edits["stacked"] = edits["ingredient_butter"] + edits["nutrient_calories"] + edits["chemical_sodium"]
    for name, modifications in edits.items():
        outputs["reformulate_" + name] = reformulate("butter_chicken", modifications, data=data)
    outputs["analyze_custom_with_typo"] = analyze({"name": "My lemonade", "ingredients": [
        {"name": "sugra", "grams": 20}, {"name": "lemon", "grams": 100}, {"name": "water", "grams": 500}]}, data)
    try:
        reformulate("not_a_dish", [], data=data)
    except MirageError as error:
        outputs["error_examples"] = [{"error": {"code": error.code, "message": str(error), "field": error.field}}]
    for name, output in outputs.items():
        (folder / f"{name}.json").write_text(json.dumps(output, indent=2, allow_nan=False) + "\n")
    print(f"Wrote {len(outputs)} examples.")


if __name__ == "__main__":
    main()
