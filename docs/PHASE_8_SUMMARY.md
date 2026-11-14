# Phase 8 summary: real RecipeDB and FlavorDB integration

The default backend now uses actual imported API responses. The earlier phases implemented and tested the full deterministic calculation engine; this phase connects real recipes and identifies which calculations the available source fields support.

## Files and functions

- `foodoscope_client.py`: bounded, cached HTTPS requests for random recipes, recipe details, title search, ingredient links, entities and molecules. `_get` handles authentication, timeout, response validation, quota limits and safe error messages. A lock protects the request counter during concurrent HTTP requests.
- `live_service.py`: `ingredient_rows` preserves reported units; `enrich_recipe` obtains exact linked FlavorDB profiles; `analyze_live` exposes source values and missing fields; `reformulate_live` applies ingredient edits; `resolve_live_source` separates saved records from user recipes.
- `catalog.py`, `engine.py`, `main.py`, `schemas.py`: actual data is the runtime default for HTTP and Python entry points. New routes fetch/search recipes. Metadata advertises available capabilities. User recipes keep user provenance. Numeric schema fields reject booleans and strings.
- `data/live_data.json`: actual Coconut Rice recipe 54264 and eight FlavorDB profiles. The demo fixture remains explicitly available for quantitative model testing.
- `scripts/probe_api.py`, `scripts/probe_flavor.py`, `scripts/sync_live_recipe.py`: bounded authenticated inspection/import commands. `scripts/live_smoke.py` replays the saved real recipe without spending more calls.
- `tests/test_live.py`: source handling, missing data, real-unit arithmetic, exact links, client caching/budget/errors, Python defaults, HTTP integration and mocked random/search routes.
- `README.md`, `docs/API_RESEARCH.md`, `docs/LIVE_TEST_REPORT.json`, `examples/live_*.json`: setup, verified routes, limitations and reproducible results. Private credentials remain ignored by Git and are absent from `.env.example`.

## Validation

Phase checkpoints: 121 tests after phase 3, 143 after phase 4, 157 after phase 5, 164 after phase 6, 166 after phase 7, and **182 after final integration**. All original 25 engine tests pass unchanged.

Authenticated upstream checks selected Coconut Rice randomly and fetched its details and linked molecular profiles. All eight profiles resolved. All eight gram weights remain unavailable because the recipe lists household units.

`python scripts/live_smoke.py`: **12 HTTP checks passed**, with zero additional upstream calls. Oil changed from 1 to 0.7 tbsp at a requested 30% reduction; stacked oil/salt edits, almond removal and legacy salt reduction passed. Unsupported nutrient cuts return `DATA_UNAVAILABLE`. Source data remains unchanged and repeated requests are deterministic.

One installed Starlette/httpx deprecation warning remains; it does not fail tests. Dependencies stay within the brief's five allowed packages.

## Decisions and what to check

The user requested only RecipeDB and FlavorDB. Their verified responses do not establish usable ingredient nutrient densities or quantitative taste strengths. Live mode therefore cannot honestly compute nutrient-cut distribution, compensator doses, nutrition savings or taste-retention percentages. It returns missing values explicitly and disables unsupported controls through metadata. No third-party nutrition dataset or guessed gram conversions are used.

Original-unit amounts extend the response with `quantities`, `unit` and `amount_basis`; unknown legacy gram fields remain null. A molecule-presence score is not a sensory score. The frontend should check capabilities and use quantity fields for live recipes.

Run `pytest -q`, then `python scripts/live_smoke.py`, and start `uvicorn main:app --reload`. Inspect `/docs`, `/api/meta`, and `/api/recipes/54264`. To exercise the full approximate nutrient/taste model, start with `MIRAGE_DATA_MODE=demo` and choose a demo dish.
