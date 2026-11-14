"""Import a real RecipeDB recipe and linked FlavorDB molecules into the default local snapshot."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import load_data, MirageError
from foodoscope_client import FoodoscopeClient, unwrap
from live_service import enrich_recipe, analyze_live
from recipe_adapter import recipe_payload


def main():
    """Fetch a bounded source snapshot, preserving unavailable fields rather than copying demo values."""
    parser = argparse.ArgumentParser(description=__doc__)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--from-probe", action="store_true")
    sources.add_argument("--recipe-id")
    sources.add_argument("--random", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    data = load_data(root / "data" / "live_data.json")
    client = FoodoscopeClient(budget=24)
    try:
        if args.from_probe:
            payload = json.loads((root / "data" / "raw" / "random_recipe.json").read_text())
        else:
            recipe_id = args.recipe_id
            if args.random:
                chosen = unwrap(client.random_recipe())
                if isinstance(chosen, list):
                    chosen = chosen[0]
                recipe_id = chosen["Recipe_id"]
            payload = client.recipe(recipe_id)
        record = enrich_recipe(payload, client)
        detail = analyze_live(record, data)
        data["dishes"][detail["dish"]] = record
        for row in detail["ingredients"]:
            profile = row.get("flavor_profile")
            data["ingredients"][row["name"]] = {"display_name": row["display_name"], "aliases": [], "category": "imported",
                "role": row["role"], "nutrients_per_g": {}, "chemicals_per_g": {}, "taste_per_g": {},
                "molecules": [item["pubchem_id"] for item in (profile or {}).get("molecules", [])],
                "data_quality": {"nutrition": "unavailable", "molecules": "flavordb" if profile else "unavailable", "taste": "unavailable"},
                "data_source": "recipedb+flavordb", "source_metadata": {"recipe_id": detail["recipe_id"], "flavor_profile": profile}}
        (root / "data" / "live_data.json").write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
        print(json.dumps({"recipe_id": detail["recipe_id"], "title": detail["display_name"], "ingredients": len(detail["ingredients"]),
                          "flavor_profiles": len(record["flavor_profiles"]), "missing_gram_weights": len(detail["data_quality"]["missing_gram_weights"]),
                          "requests_made": client.requests_made, "source_issues": record["source_issues"]}))
    except MirageError as error:
        print(json.dumps({"error": error.code, "message": str(error), "requests_made": client.requests_made}))
        sys.exit(1)
    finally:
        client.close()


if __name__ == "__main__":
    main()
