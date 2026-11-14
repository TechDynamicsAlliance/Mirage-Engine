"""Exercise the real HTTP boundary without any upstream calls."""
import pytest
from fastapi.testclient import TestClient
from main import app
import main
from catalog import load_data

client = TestClient(app)


@pytest.fixture(autouse=True)
def demo_catalog(monkeypatch):
    """Exercise the complete numerical contract using explicitly labelled offline fixtures."""
    monkeypatch.setattr(main, "DATA", load_data())


def test_health_meta_dishes_details_and_autocomplete():
    """Picker data and ingredient detail should be usable without frontend calculations."""
    assert client.get("/health").json() == {"status": "ok", "engine": "mirage", "version": "1.0.0"}
    assert client.get("/api/meta").json()["limits"]["max_modifications"] == 8
    assert len(client.get("/api/dishes").json()) == 8
    detail = client.get("/api/dishes/butter_chicken").json()
    assert {"totals", "per_serving", "modifiable", "dv_pct", "badges"} <= detail.keys()
    assert detail["ingredients"][0]["is_core"]
    assert all(0 <= row["max_feasible_percent"] <= 80 for row in detail["modifiable"]["nutrients"])
    assert client.get("/api/ingredients?q=vanilla").json()[0]["name"] == "vanilla_extract"


def test_custom_typo_and_both_reformulation_styles():
    """Unknown foods receive suggestions; old and new request formats both reach the engine."""
    detail = client.post("/api/analyze", json={"custom_recipe": {"name": "Test", "ingredients": [{"name": "sugra", "grams": 20}]}}).json()
    assert "sugar" in detail["unresolved_ingredients"][0]["suggestions"]
    for request in ({"dish": "lemonade", "goal": "sugar", "reduce_percent": 20},
                    {"dish": "lemonade", "modifications": [{"type": "ingredient", "target": "sugar", "action": "reduce", "percent": 20}]}):
        response = client.post("/api/reformulate", json=request)
        assert response.status_code == 200
        assert response.json()["new_recipe"]["ingredients"]["sugar"] == 40
        assert response.json()["schema_version"] == 2


@pytest.mark.parametrize("body,code", [
    ({}, "INVALID_REQUEST"),
    ({"dish": "absent"}, "DISH_NOT_FOUND"),
    ({"custom_recipe": {"name": "Empty", "ingredients": []}}, "INVALID_RECIPE"),
    ({"dish": "lemonade", "modifications": [{"type": "ingredient", "target": "butter", "action": "remove"}]}, "UNKNOWN_INGREDIENT_TARGET"),
    ({"dish": "lemonade", "modifications": [{"type": "nutrient", "target": "unknown", "action": "reduce", "percent": 20}]}, "UNKNOWN_NUTRIENT"),
    ({"dish": "lemonade", "modifications": [{"type": "chemical", "target": "unknown", "action": "reduce", "percent": 20}]}, "UNKNOWN_CHEMICAL"),
    ({"dish": "lemonade", "modifications": [{"type": "chemical", "target": "caffeine_mg", "action": "reduce", "percent": 20}]}, "TARGET_NOT_PRESENT"),
    ({"dish": "lemonade", "goal": "sugar", "reduce_percent": 81}, "PERCENT_OUT_OF_RANGE"),
    ({"dish": "lemonade", "modifications": [{"type": "ingredient", "target": "sugar", "action": "remove"}] * 2}, "DUPLICATE_MODIFICATION"),
    ({"dish": "lemonade", "modifications": [{}] * 9}, "TOO_MANY_MODIFICATIONS"),
    ({"dish": "lemonade", "options": {"max_compensators": 6}}, "INVALID_REQUEST"),
])
def test_error_codes_share_one_shape(body, code):
    """Every expected domain error exposes a code, message and actionable field."""
    response = client.post("/api/reformulate", json=body)
    assert response.status_code == (404 if code == "DISH_NOT_FOUND" else 422)
    error = response.json()["error"]
    assert set(error) == {"code", "message", "field"}
    assert error["code"] == code


def test_validation_errors_and_missing_routes_share_shape():
    """Framework failures must not fall back to FastAPI's incompatible detail envelope."""
    assert client.get("/api/ingredients?limit=0").json()["error"]["code"] == "INVALID_REQUEST"
    assert client.post("/api/analyze", content="bad json", headers={"Content-Type": "application/json"}).json()["error"]["code"] == "INVALID_REQUEST"
    assert client.get("/missing").json()["error"]["code"] == "INVALID_REQUEST"
