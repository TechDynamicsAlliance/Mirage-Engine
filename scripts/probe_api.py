"""Fetch one random real recipe and save raw evidence locally without credentials."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import MirageError
from foodoscope_client import FoodoscopeClient, unwrap


def main():
    """Inspect the real schema using at most two requests so adapter work has concrete evidence."""
    client = FoodoscopeClient(budget=2)
    try:
        source = unwrap(client.random_recipe())
        if isinstance(source, list):
            source = source[0]
        recipe_id = source["Recipe_id"]
        detail = client.recipe(recipe_id)
        path = Path(__file__).resolve().parents[1] / "data" / "raw"
        path.mkdir(parents=True, exist_ok=True)
        (path / "random_recipe.json").write_text(json.dumps(detail, indent=2))
        body = detail.get("payload", detail)
        print(json.dumps({"id": recipe_id, "title": source.get("Recipe_title"), "keys": list(body),
                          "ingredient_sample": body.get("ingredients", [])[:3], "requests": client.requests_made}))
    except MirageError as error:
        print(json.dumps({"error": error.code, "message": str(error), "requests": client.requests_made}))
        sys.exit(1)
    finally:
        client.close()


if __name__ == "__main__":
    if "--inspect" in sys.argv:
        client = FoodoscopeClient(budget=4)
        folder = Path(__file__).resolve().parents[1] / "data" / "raw"
        try:
            nutrition = client._get("/recipe2-api/recipe-nutri/nutritioninfo", {"page": 1, "limit": 10})
            (folder / "nutrition_probe.json").write_text(json.dumps(nutrition, indent=2))
            rows = unwrap(nutrition)
            print("Nutrition shape:", type(rows).__name__, str(rows)[:220])
            links = client.links("olive oil")
            (folder / "flavor_links_probe.json").write_text(json.dumps(links, indent=2))
            rows = unwrap(links)
            print("Links shape:", type(rows).__name__, str(rows)[:1600])
            if isinstance(rows, list):
                matched = next((row for row in rows if row.get("recipe", {}).get("ingredient", "").lower() == "olive oil"), None)
                if matched:
                    entity_id = matched.get("entity", {}).get("entity_id") or matched.get("recipe", {}).get("flavordb_id")
                    if entity_id is not None:
                        molecules = client.molecules(entity_id)
                        (folder / "flavor_molecules_probe.json").write_text(json.dumps(molecules, indent=2))
                        print("Molecules shape:", type(unwrap(molecules)).__name__, str(unwrap(molecules))[:500])
            print("Requests:", client.requests_made)
        except MirageError as error:
            print(error.code, str(error))
            sys.exit(1)
        finally:
            client.close()
    else:
        main()
