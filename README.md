# MIRAGE backend

Python 3.10+ recipe reformulation using RecipeDB ingredient quantities and FlavorDB molecule associations. The default HTTP API and Python facade use actual imported source data. The saved random recipe is **Coconut Rice, RecipeDB 54264**, with eight linked FlavorDB profiles.

## Setup and run

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
uvicorn main:app --reload
```

Open [interactive API documentation](http://127.0.0.1:8000/docs). The health route is `/health`.
Use `/api/dishes`, `/api/dishes/{dish}`, `/api/meta` and `/api/ingredients` to build a recipe picker.
POST `/api/analyze` accepts exactly one of `dish`, `recipe_id` or `custom_recipe`.

```json
{"recipe_id":"54264","modifications":[{"type":"ingredient","target":"olive_oil","action":"reduce","percent":30}],"options":{"include_trace":true}}
```

Send this body to POST `/api/reformulate`. The legacy body
`{"recipe_id":"54264","goal":"salt","reduce_percent":20}` also works.
All failures return `{"error":{"code":"...","message":"...","field":"..."}}`.

## What the real data supports

Ingredient reductions and removals work in the original reported units. For example, the request above changes olive oil from **1 tbsp to 0.7 tbsp**. `new_recipe.quantities` contains those amounts; gram fields remain `null` when the source provides no verified conversion. Mass units convert directly. Molecule overlap uses actual PubChem IDs, and does not measure taste retention.

Only RecipeDB and FlavorDB are used, as requested. The verified responses do not provide ingredient nutrient densities with a usable quantity basis, or quantitative taste strengths. Consequently:

- Recipe-level reported nutrition is available in analysis; missing metrics remain `null`.
- Nutrient and chemical cuts return `422 DATA_UNAVAILABLE` in real-data mode.
- Reformulated nutrition, savings and taste-retention scores remain `null`; no compensator amounts are invented.
- `/api/meta.capabilities` and each response's `data_quality` describe these limits. A flavor presence score of 100% means the same known molecules remain, even if ingredient amounts decrease.

Per-serving values divide reported recipe totals by numeric source servings. Free-text yields fall back to one whole recipe with a warning. RecipeDB's `Calories` field is not interchanged with `Energy (kcal)`. These source values have not been independently measured or reconciled.

## Fetching other real recipes

Set `FOODOSCOPE_API_KEY` in your process environment to your existing key. An ignored local `data/local_api_credentials.json` is also supported; never commit it. No `.env` loading is required. The default base URL is `https://api.foodoscope.com`.

- `GET /api/recipes/random`: choose a real recipe, fetch its ingredients and enrich linked FlavorDB profiles.
- `GET /api/recipes/search?q=rice`: RecipeDB title search.
- `GET /api/recipes/{recipe_id}`: details and molecular associations.
- POST `/api/analyze` or `/api/reformulate` with `recipe_id`: use the saved record or fetch that recipe.

To add recipes to the saved catalog, run either command and restart the server:

```sh
python scripts/sync_live_recipe.py --recipe-id 54264
python scripts/sync_live_recipe.py --random
```

The snapshot works without an API key. New fetches require credentials. HTTP responses are cached for 24 hours; the saved `data/live_data.json` snapshot persists until explicitly refreshed by the import script. Random selections are not cached. There are no automatic retries. Each server process permits 40 uncached upstream requests, and each import permits 24, to bound quota use. A recipe can need two calls per linked ingredient plus selection/detail calls. Missing mappings or exhausted enrichment budgets appear in `source_issues`; authentication failures stop the request. HTTP 429 becomes `UPSTREAM_RATE_LIMIT`. Cache and private credentials are ignored by Git.

## Verification and demo mode

```sh
pytest -q
python scripts/live_smoke.py
```

The smoke script replays the previously fetched random recipe through 12 HTTP checks without spending API calls. See [the test report](docs/LIVE_TEST_REPORT.json) and `examples/live_*.json` for actual source-backed output. Ordinary tests use labelled fixtures and mocked network transport.

The complete nutrient distribution, chemical reduction, taste repair, warnings and comparison engine remains available with explicitly labelled approximation fixtures:

```sh
MIRAGE_DATA_MODE=demo uvicorn main:app --reload
python scripts/dump_examples.py
```

In demo mode, use dishes such as `butter_chicken` and `lemonade`. `load_data()` explicitly loads the legacy demo fixture for tests; `analyze`, `reformulate`, and `list_dishes` default to the runtime source mode. Pass `data=load_data()` to evaluate the demo directly in Python. The pure calculations make no network calls.

See [the engine walkthrough](docs/ENGINE_EXPLAINED.md), [API research and live findings](docs/API_RESEARCH.md), and the phase summaries in `docs/`. Demo taste-equivalence values are heuristic approximations. Daily-reference percentages are approximate; read the provenance and warnings before interpreting a result.
