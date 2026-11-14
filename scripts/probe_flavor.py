"""Inspect two documented FlavorDB routes without printing authorization headers."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from foodoscope_client import FoodoscopeClient, unwrap
from catalog import MirageError


def main():
    """Try the direct entity route and linked mapping to observe exact live response shapes."""
    client = FoodoscopeClient(budget=3)
    folder = Path(__file__).resolve().parents[1] / "data" / "raw"
    try:
        for label, path, params in [("entity", "/flavordb/entities/by-entity-alias-readable", {"entity_alias_readable": "olive"}),
                                    ("links", "/recipe2-api/connections/links", {"ingredient": "olive oil"})]:
            try:
                payload = client._get(path, params)
                (folder / f"flavor_{label}_probe.json").write_text(json.dumps(payload, indent=2))
                rows = unwrap(payload)
                print(label, str(rows)[:2500])
            except MirageError as error:
                print(label, error.code, str(error))
        molecules = client.molecules(307)
        (folder / "flavor_molecules_probe.json").write_text(json.dumps(molecules, indent=2))
        print("molecules", str(unwrap(molecules))[:500])
    except MirageError as error:
        print(error.code, str(error))
        sys.exit(1)
    finally:
        client.close()


if __name__ == "__main__":
    main()
