"""Offline contract tests for real-data mode; fixtures are explicitly artificial."""
from copy import deepcopy
import json
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
from catalog import MirageError, load_data
from foodoscope_client import FoodoscopeClient
from live_service import analyze_live, reformulate_live, enrich_recipe
import main
import engine


@pytest.fixture
def definitions():
    """Use the real-mode metric definitions without depending on a particular imported recipe."""
    data = load_data(Path(__file__).resolve().parents[1] / "data" / "live_data.json")
    data["dishes"] = {}
    return data


@pytest.fixture
def record():
    """Supply a made-up source record with household quantities and no ingredient densities."""
    return {"payload": {"data": {"recipe": {"Recipe_id": "999", "Recipe_title": "Artificial test rice", "servings": "2", "Energy (kcal)": "400"},
            "ingredients": [{"ingredient": "rice", "quantity": "1", "unit": "cup", "M_or_A": "M"},
                            {"ingredient": "olive oil", "quantity": "1", "unit": "tablespoon", "M_or_A": "A"},
                            {"ingredient": "salt", "quantity": "2", "unit": "g", "M_or_A": "A"}]}},
            "flavor_profiles": {}, "source_issues": []}


def test_live_analysis_never_treats_missing_amounts_as_zero(record, definitions):
    """Source-level totals can be shown while unsupported ingredient measurements stay null."""
    detail = analyze_live(record, definitions)
    assert detail["totals"]["nutrients"]["calories_kcal"] == 400
    assert detail["totals"]["nutrients"]["sugar_g"] is None
    assert detail["ingredients"][0]["grams"] is None
    assert detail["ingredients"][2]["grams"] == 2
    assert not detail["data_quality"]["placeholder_values"]
    assert not detail["data_quality"]["ingredient_nutrition_available"]
    assert detail["modifiable"]["nutrients"] == []


def test_live_edits_use_actual_units_and_have_no_fabricated_scores(record, definitions):
    """Cut a tablespoon quantity exactly and retain null nutrition and taste predictions."""
    before = deepcopy(record)
    edits = [{"type": "ingredient", "target": "olive oil", "action": "reduce", "percent": 30}]
    result = reformulate_live(record, edits, {}, definitions)
    assert result["new_recipe"]["quantities"]["olive_oil"] == {"amount": .7, "unit": "tbsp"}
    assert result["new_recipe"]["ingredients"]["olive_oil"] is None
    assert result["scores"]["taste_retention_pct"] is None
    assert result["nutrition"]["fat_saved_g"] is None
    assert result["added_compensators"] == []
    assert result["trace"] == [row["text"] for row in result["trace_detail"]]
    assert result == reformulate_live(record, edits, {}, definitions)
    assert record == before
    json.dumps(result, allow_nan=False)


def test_live_core_remove_and_legacy_salt(record, definitions):
    """Explicit removal changes molecular presence and core identity; legacy salt still cuts grams."""
    result = reformulate_live(record, [{"type": "ingredient", "target": "rice", "action": "remove"}], {}, definitions)
    assert "rice" not in result["new_recipe"]["quantities"]
    assert any(row["code"] == "CORE_INGREDIENT_CHANGED" for row in result["warning_details"])
    result = reformulate_live(record, None, {"include_trace": False}, definitions, goal="salt", reduce_percent=50)
    assert result["new_recipe"]["ingredients"]["salt"] == 1
    assert result["trace"] == []


def test_live_metric_cut_is_explicitly_unavailable(record, definitions):
    """Reported recipe totals alone must not authorize invented ingredient-level metric cuts."""
    with pytest.raises(MirageError) as error:
        reformulate_live(record, [{"type": "nutrient", "target": "fat_g", "action": "reduce", "percent": 30}], {}, definitions)
    assert error.value.code == "DATA_UNAVAILABLE"


def test_client_cache_budget_auth_and_exact_routes(tmp_path):
    """Cached reads cost no requests and route construction never includes the credential in URLs."""
    calls = []
    def handler(request):
        """Record a mocked request so no paid API is used by ordinary pytest runs."""
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer test-only-key"
        return httpx.Response(200, json={"data": {"Recipe_id": "123"}})
    client = FoodoscopeClient("test-only-key", cache_dir=tmp_path, budget=1, transport=httpx.MockTransport(handler))
    assert client.recipe("123") == client.recipe("123")
    assert client.requests_made == len(calls) == 1
    assert calls[0].url.path == "/recipe2-api/search-recipe/123"
    assert "test-only-key" not in str(calls[0].url)
    assert "test-only-key" not in next(tmp_path.glob("*.json")).read_text()
    with pytest.raises(MirageError) as error:
        client.recipe("456")
    assert error.value.code == "API_BUDGET_EXCEEDED"
    client.close()


@pytest.mark.parametrize("status,code", [(401,"UPSTREAM_AUTH_ERROR"),(403,"UPSTREAM_AUTH_ERROR"),(429,"UPSTREAM_RATE_LIMIT"),(500,"UPSTREAM_UNAVAILABLE")])
def test_client_errors_do_not_leak_response_or_secret(status, code, tmp_path):
    """Untrusted upstream failure bodies must never expose credentials through our API."""
    def handler(request):
        """Return a deliberately sensitive fake response to exercise redaction-by-omission."""
        return httpx.Response(status, json={"message": "test-secret"})
    client = FoodoscopeClient("test-secret", cache_dir=tmp_path, transport=httpx.MockTransport(handler))
    with pytest.raises(MirageError) as error:
        client.recipe("1")
    assert error.value.code == code
    assert "test-secret" not in str(error.value)
    client.close()


def test_flavor_enrichment_requires_exact_recipe_link(record, tmp_path):
    """Do not silently accept a different food from a substring search result."""
    def handler(request):
        """Supply a misleading first link and the correct second one to test exact association."""
        if request.url.path.endswith("/links"):
            ingredient = request.url.params["ingredient"]
            return httpx.Response(200, json={"payload": {"data": [
                {"recipe": {"ingredient": "other food"}, "entity": {"entity_id": 1}, "isLinked": True},
                {"recipe": {"ingredient": ingredient}, "entity": {"entity_id": 2}, "isLinked": True}]}})
        assert request.url.path == "/flavordb/entities/by-id/2/molecules-compact"
        return httpx.Response(200, json=[{"pubchem_id": 123, "common_name": "artificial fixture molecule"}])
    client = FoodoscopeClient("test", cache_dir=tmp_path, transport=httpx.MockTransport(handler))
    result = enrich_recipe(record["payload"], client)
    assert len(result["flavor_profiles"]) == 3
    assert all(profile["entity_id"] == 2 for profile in result["flavor_profiles"].values())
    assert client.requests_made == 4  # Three ingredient links, one shared molecule response.
    client.close()


def test_live_endpoints_and_no_placeholder_fallback(record, definitions, monkeypatch):
    """Saved real records work through HTTP; missing IDs must not resolve to demo dishes."""
    definitions["dishes"] = {"recipedb_999": record}
    monkeypatch.setattr(main, "DATA", definitions)
    client = TestClient(main.app)
    assert client.get("/api/dishes").json()[0]["recipe_id"] == "999"
    assert client.get("/api/dishes/lemonade").status_code == 404
    assert client.get("/api/recipes/999").status_code == 200
    response = client.post("/api/reformulate", json={"recipe_id": "999", "modifications": [
        {"type": "ingredient", "target": "olive_oil", "action": "reduce", "percent": 30}]})
    assert response.status_code == 200
    assert response.json()["new_recipe"]["quantities"]["olive_oil"]["amount"] == .7
    response = client.post("/api/reformulate", json={"recipe_id": "999", "modifications": [
        {"type": "chemical", "target": "sodium_mg", "action": "reduce", "percent": 30}]})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DATA_UNAVAILABLE"


def test_python_facade_defaults_to_real_snapshot(record, definitions, monkeypatch):
    """Python and HTTP callers share source-only behavior rather than quietly loading demo values."""
    definitions["dishes"] = {"recipedb_999": record}
    monkeypatch.setattr(engine, "load_runtime_data", lambda: definitions)
    assert engine.analyze("recipedb_999")["data_source"] == "recipedb+flavordb"
    assert engine.list_dishes()[0]["dish"] == "recipedb_999"
    result = engine.reformulate("recipedb_999", "salt", 50)
    assert result["new_recipe"]["ingredients"]["salt"] == 1
    with pytest.raises(MirageError, match="quantitative baseline"):
        engine.analyze_baseline("recipedb_999")
    with pytest.raises(MirageError) as error:
        engine.analyze("lemonade")
    assert error.value.code == "DISH_NOT_FOUND"


def test_custom_recipe_has_user_provenance(definitions, monkeypatch):
    """User grams stay usable without claiming their recipe was fetched from RecipeDB."""
    monkeypatch.setattr(main, "DATA", definitions)
    client = TestClient(main.app)
    source = {"name": "My rice", "servings": 2, "tags": ["custom"],
              "ingredients": [{"name": "rice", "grams": 100}]}
    detail = client.post("/api/analyze", json={"custom_recipe": source}).json()
    assert detail["data_source"] == "user"
    assert detail["source_metadata"]["recipedb_endpoint"] is None
    assert detail["recipe_id"] is None
    assert detail["tags"] == ["custom"]
    assert all(value is None for value in detail["totals"]["nutrients"].values())
    result = client.post("/api/reformulate", json={"custom_recipe": source, "modifications": [
        {"type": "ingredient", "target": "rice", "action": "reduce", "percent": 25}]}).json()
    assert result["data_source"] == "user"
    assert result["new_recipe"]["ingredients"]["rice"] == 75


def test_random_search_and_error_routing(record, definitions, tmp_path, monkeypatch):
    """Exercise actual client-to-HTTP wiring with mock transport and bounded upstream calls."""
    def handler(request):
        """Return distinct documented response shapes for random selection, details and search."""
        path = request.url.path
        if path.endswith("recipeofday"):
            return httpx.Response(200, json={"payload": {"data": {"Recipe_id": "999"}}})
        if path.endswith("search-recipe/999"):
            return httpx.Response(200, json=record["payload"])
        if path.endswith("/links"):
            return httpx.Response(200, json={"payload": {"data": []}})
        if path.endswith("recipeByTitle"):
            assert request.url.params["title"] == "rice"
            return httpx.Response(200, json={"payload": {"data": [{"Recipe_id": "999"}]}})
        return httpx.Response(401, json={"message": "test-secret"})
    upstream = FoodoscopeClient("test-secret", cache_dir=tmp_path, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(main, "DATA", definitions)
    monkeypatch.setattr(main, "UPSTREAM", upstream)
    client = TestClient(main.app)
    result = client.get("/api/recipes/random")
    assert result.status_code == 200
    assert result.json()["recipe_id"] == "999"
    assert len(result.json()["data_quality"]["missing_flavor_profiles"]) == 3
    assert client.get("/api/recipes/search", params={"q": "rice"}).status_code == 200
    result = client.get("/api/recipes/888")
    assert result.status_code == 503
    assert result.json()["error"]["code"] == "UPSTREAM_AUTH_ERROR"
    assert "test-secret" not in result.text
    assert not client.get("/api/meta").json()["capabilities"]["demo_mode"]
    upstream.close()


@pytest.mark.parametrize("percent", [True, "30"])
def test_http_legacy_percent_rejects_coercion(record, definitions, monkeypatch, percent):
    """Reject booleans and numeric strings before schema coercion can hide invalid input."""
    definitions["dishes"] = {"recipedb_999": record}
    monkeypatch.setattr(main, "DATA", definitions)
    result = TestClient(main.app).post("/api/reformulate", json={"recipe_id": "999", "goal": "salt", "reduce_percent": percent})
    assert result.status_code == 422
