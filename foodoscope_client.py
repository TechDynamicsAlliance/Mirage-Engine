"""Bounded, cached Foodoscope requests; the calculation engine stays network-free."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from threading import Lock
import time

import httpx

from catalog import MirageError

ROOT = Path(__file__).resolve().parent
DEFAULT_BASE_URL = "https://api.foodoscope.com"


class FoodoscopeClient:
    """Own the network boundary, credentials and request budget independently of recipe math."""

    def __init__(self, api_key=None, *, base_url=None, cache_dir=None, budget=40, transport=None, ttl=86400):
        """Read configured credentials without logging them and prepare a bounded HTTPS client."""
        if api_key is None:
            api_key = os.environ.get("FOODOSCOPE_API_KEY", "")
            private = ROOT / "data" / "local_api_credentials.json"
            if not api_key and private.exists():
                api_key = json.loads(private.read_text()).get("api_key", "")
        self.api_key = api_key
        self.base_url = (base_url or os.environ.get("FOODOSCOPE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        if not self.base_url.startswith("https://"):
            raise MirageError("Foodoscope requires an HTTPS base URL.", "API_NOT_CONFIGURED", "FOODOSCOPE_BASE_URL")
        self.cache_dir = Path(cache_dir) if cache_dir is not None else ROOT / ".foodoscope_cache"
        self.budget = budget
        self.requests_made = 0
        self._budget_lock = Lock()
        self.ttl = ttl
        self.client = httpx.Client(transport=transport, timeout=20, follow_redirects=False)

    def close(self):
        """Release HTTP connections when the application shuts down."""
        self.client.close()

    def _get(self, path: str, params=None, *, cache=True):
        """Use cached JSON or spend one request, never retrying or leaking upstream credentials."""
        params = params or {}
        cache_key = hashlib.sha256(json.dumps([self.base_url, path, params], sort_keys=True).encode()).hexdigest()
        cache_path = self.cache_dir / f"{cache_key}.json"
        if cache and cache_path.exists():
            try:
                stored = json.loads(cache_path.read_text())
                if time.time() - stored["saved_at"] <= self.ttl:
                    return deepcopy(stored["response"])
            except (ValueError, KeyError, TypeError, OSError):
                pass
        if not self.api_key:
            raise MirageError("Configure FOODOSCOPE_API_KEY to fetch live data.", "API_NOT_CONFIGURED", "FOODOSCOPE_API_KEY")
        with self._budget_lock:
            if self.requests_made >= self.budget:
                raise MirageError("The local upstream request budget was reached; cached recipes still work.", "API_BUDGET_EXCEEDED", "upstream")
            self.requests_made += 1
        try:
            response = self.client.get(self.base_url + path, params=params,
                                       headers={"Authorization": f"Bearer {self.api_key}"})
        except httpx.HTTPError:
            raise MirageError("Foodoscope could not be reached.", "UPSTREAM_UNAVAILABLE", "upstream") from None
        errors = {401: "UPSTREAM_AUTH_ERROR", 403: "UPSTREAM_AUTH_ERROR", 404: "UPSTREAM_NOT_FOUND", 429: "UPSTREAM_RATE_LIMIT"}
        if response.status_code != 200:
            raise MirageError(f"Foodoscope returned HTTP {response.status_code}.",
                              errors.get(response.status_code, "UPSTREAM_UNAVAILABLE"), "upstream")
        try:
            payload = response.json()
            json.dumps(payload, allow_nan=False)
        except (ValueError, TypeError):
            raise MirageError("Foodoscope returned invalid JSON.", "UPSTREAM_INVALID_RESPONSE", "upstream") from None
        if not isinstance(payload, (dict, list)) or (isinstance(payload, dict) and payload.get("success") in (False, "false")):
            raise MirageError("Foodoscope did not return a successful data response.", "UPSTREAM_INVALID_RESPONSE", "upstream")
        if cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", dir=self.cache_dir, delete=False) as handle:
                json.dump({"saved_at": time.time(), "response": payload}, handle, allow_nan=False)
                temporary = handle.name
            os.replace(temporary, cache_path)
        return payload

    def random_recipe(self):
        """Ask RecipeDB for a random recipe; randomness is confined to selecting source data."""
        return self._get("/recipe2-api/recipe/recipeofday", cache=False)

    def recipe(self, recipe_id):
        """Retrieve full ingredient details for a validated numeric RecipeDB identifier."""
        return self._get(f"/recipe2-api/search-recipe/{self._identifier(recipe_id)}")

    def search(self, title):
        """Search the documented title endpoint so users can choose a real recipe."""
        return self._get("/recipe2-api/recipe-bytitle/recipeByTitle", {"title": title})

    def links(self, ingredient):
        """Use explicit cross-database links instead of guessing a FlavorDB identity."""
        return self._get("/recipe2-api/connections/links", {"ingredient": ingredient})

    def entity(self, name):
        """Look up a FlavorDB readable name when no RecipeDB link is available."""
        return self._get("/flavordb/entities/by-entity-alias-readable", {"entity_alias_readable": name})

    def molecules(self, entity_id):
        """Fetch stable PubChem IDs and names for molecular-overlap calculations."""
        return self._get(f"/flavordb/entities/by-id/{self._identifier(entity_id)}/molecules-compact")

    @staticmethod
    def _identifier(value):
        """Restrict path IDs to digits so user input cannot escape a documented route."""
        if not re.fullmatch(r"[0-9]+", str(value)):
            raise MirageError("Use a numeric database ID.", "INVALID_REQUEST", "recipe_id")
        return str(value)


def unwrap(payload):
    """Read the observed Foodoscope wrappers while retaining sibling ingredient arrays elsewhere."""
    if isinstance(payload, dict):
        payload = payload.get("payload", payload)
        if isinstance(payload, dict):
            return payload.get("data", payload)
    return payload
