"""Replay the genuinely imported random RecipeDB recipe through HTTP without spending API calls."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
import main


def main_test():
    """Verify source quantities, flavor coverage and missing-data handling; save reproducible evidence."""
    root = Path(__file__).resolve().parents[1]
    assert main.DATA["meta"]["data_source"] != "placeholder", "Run without MIRAGE_DATA_MODE=demo."
    before = deepcopy(main.DATA)
    calls_before = main.UPSTREAM.requests_made
    client = TestClient(main.app)
    checks = []

    def request(method, path, expected=200, body=None):
        """Check the public HTTP response and record only safe, compact test evidence."""
        response = client.request(method, path, json=body)
        assert response.status_code == expected, (path, response.status_code, response.text[:300])
        payload = response.json()
        json.dumps(payload, allow_nan=False)
        checks.append({"method": method, "path": path, "expected_status": expected, "actual_status": response.status_code})
        return payload

    request("GET", "/health")
    meta = request("GET", "/api/meta")
    assert not meta["capabilities"]["nutrient_edits"]
    dishes = request("GET", "/api/dishes")
    assert any(dish["recipe_id"] == "54264" for dish in dishes)
    detail = request("GET", "/api/recipes/54264")
    assert detail["display_name"] == "Coconut Rice"
    assert len(detail["ingredients"]) == 8
    assert not detail["data_quality"]["missing_flavor_profiles"]
    assert all(row["grams"] is None for row in detail["ingredients"])
    assert detail == request("POST", "/api/analyze", body={"recipe_id": "54264"})
    body = {"recipe_id": "54264", "modifications": [
        {"type": "ingredient", "target": "olive_oil", "action": "reduce", "percent": 30}]}
    edited = request("POST", "/api/reformulate", body=body)
    assert edited["original_recipe"]["quantities"]["olive_oil"] == {"amount": 1.0, "unit": "tbsp"}
    assert edited["new_recipe"]["quantities"]["olive_oil"] == {"amount": .7, "unit": "tbsp"}
    assert edited["scores"]["taste_retention_pct"] is None
    assert edited["nutrition"]["fat_saved_g"] is None
    assert edited["scores"]["flavor_preserved_pct"] == 100.0
    assert edited["added_compensators"] == []
    assert edited == request("POST", "/api/reformulate", body=body)
    stacked = request("POST", "/api/reformulate", body={"recipe_id": "54264", "modifications": [
        {"type": "ingredient", "target": "olive_oil", "action": "reduce", "percent": 30},
        {"type": "ingredient", "target": "salt", "action": "reduce", "percent": 50}]})
    assert stacked["new_recipe"]["quantities"]["salt"]["amount"] == .25
    removed = request("POST", "/api/reformulate", body={"recipe_id": "54264", "modifications": [
        {"type": "ingredient", "target": "almond", "action": "remove"}]})
    assert "almond" not in removed["new_recipe"]["quantities"]
    legacy = request("POST", "/api/reformulate", body={"recipe_id": "54264", "goal": "salt", "reduce_percent": 30})
    assert legacy["new_recipe"]["quantities"]["salt"]["amount"] == .35
    error = request("POST", "/api/reformulate", expected=422, body={"recipe_id": "54264", "modifications": [
        {"type": "nutrient", "target": "fat_g", "action": "reduce", "percent": 30}]})
    assert error["error"]["code"] == "DATA_UNAVAILABLE"
    request("GET", "/api/dishes/lemonade", expected=404)
    assert before == main.DATA
    assert main.UPSTREAM.requests_made == calls_before
    artifacts = {"live_coconut_rice_analysis.json": detail, "live_coconut_rice_reformulated.json": edited,
                 "live_coconut_rice_stacked.json": stacked, "live_unavailable_nutrient_error.json": error}
    for filename, payload in artifacts.items():
        (root / "examples" / filename).write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    report = {"tested_at": datetime.now(timezone.utc).isoformat(), "status": "passed", "recipe_id": "54264",
              "title": detail["display_name"], "selection": "Previously selected by authenticated RecipeDB recipeofday",
              "test_mode": "HTTP replay of saved actual RecipeDB and FlavorDB responses; no fresh upstream requests",
              "ingredients": 8, "linked_flavor_profiles": 8, "missing_gram_weights": 8,
              "new_upstream_requests": main.UPSTREAM.requests_made - calls_before,
              "assertions": ["30% olive oil reduction: 1 to 0.7 tbsp", "Stacked salt and oil edits",
                             "Almond removal", "Legacy salt reduction", "No invented nutrition or taste scores",
                             "Unsupported nutrient cut returns DATA_UNAVAILABLE", "Determinism", "Input immutability", "Finite JSON"],
              "http_checks": checks}
    (root / "docs" / "LIVE_TEST_REPORT.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "recipe": report["title"], "http_checks": len(checks),
                      "upstream_requests": report["new_upstream_requests"]}))


if __name__ == "__main__":
    main_test()
