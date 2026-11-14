# MIRAGE engine v2 — plan (Phase 0)

Rebuild the engine so a caller can name a dish (or type a recipe), see ingredients, nutrients, and chemicals, then cut or remove items. The engine applies the cuts, repairs lost taste, and returns a before/after payload the frontend can draw as-is. No network. Same inputs always give the same output. Existing response keys stay; we only add keys.

`engine.py` stays the front door (`analyze`, `reformulate`, `list_dishes`, `load_data`, `MirageError`, `DishNotFound`) because `test_engine.py` and `main.py` already import it. Helpers move out so each file has one job.

## Files

| When | File | Role |
|---|---|---|
| 1 | `scripts/migrate_placeholder_data.py` | One-off: old keys → schema v2. Then the JSON is edited by hand up to 8 dishes and ~45–60 ingredients. |
| 1 | `data/placeholder_data.json` | `meta`, `taste_axes`, `nutrient_defs`, `chemical_defs`, `mechanisms`, richer `ingredients`, `dishes`. |
| 1 | `requirements.txt`, `tests/test_data.py` | Allowed libraries. Catalog rules (calories, aliases, caps, cores). |
| 2 | `catalog.py`, `metrics.py`, `modify.py` | Load, names, recipe checks. Totals and contributions. Parse and apply cuts (steps 1–5). |
| 2 | `tests/test_modify.py` | Cuts, locks, duplicates, groups, `already_satisfied`. |
| 3 | `taste.py`, `warning_rules.py` | Deficits, ranking, caps, scores. Warning codes and badges. |
| 3 | `tests/test_taste.py` | Fat now repairs richness. Zest skipped. Caps and excludes hold. |
| 4 | `compare.py` | One function builds the full response, including legacy keys. |
| 4 | `tests/test_output.py` | Invariants, sweep, determinism. Legacy `reformulate` switches to this pipeline here, not before. |
| 5 | `schemas.py`, `main.py`, `tests/test_api.py` | Models, routes, error shape `{"error": {code, message, field}}`. |
| 5 | `scripts/dump_examples.py`, `examples/`, `README.md`, `docs/ENGINE_EXPLAINED.md` | Sample JSON, setup, the 7 steps on lemonade. |

Not created: `.env`, `foodoscope_client.py`, `cache_manager.py`. Phases 6–7 (`units.py`, `recipe_adapter.py`) wait until you ask.

## Functions

- **catalog:** `load_data`, `validate_catalog`, `normalize_name`, `resolve_name`, `resolve_recipe`, `search_ingredients`
- **metrics:** `totals`, `contributions`, `per_serving`, `taste_vector`, `fingerprint`, `dv_percent`, `badges`, `feasible_percent`
- **modify:** `parse_modifications`, `apply_ingredient_mods`, `apply_metric_mods`
- **taste:** `deficits`, `rank_compensators`, `repair`
- **warning_rules:** `build_warnings` (thresholds as constants at the top)
- **compare:** `build_response`
- **engine:** `analyze`, `reformulate`, `list_dishes`

## Risks

1. **Call shape.** Tests call `reformulate("lemonade", "sugar", 20, DATA)`. `main.py` uses keywords `dish=`, `goal=`, `reduce_percent=`. The new signature is `reformulate(source, modifications=None, options=None, data=None, *, goal=None, reduce_percent=None)`. A string in the second slot means the old call. Keyword `dish` is accepted as an alias of `source` so the API file still runs before Phase 5.
2. **Fat behavior changes on purpose.** Today fat cuts every ingredient over 0.1 g fat/g and returns null taste scores. V2 cuts `fat_g` with the shared rules (core and aromatic locked) and repairs richness, so scores become numbers. Current fat tests only check that fat drops. None assert null scores.
3. **Lemonade and tomato soup must not drift.** Their tests expect compensators, retention above 50, and a 10% sugar cut that still hits 95%. Sweet and salty numbers stay as they are. Those dishes get no extra affected axis, so the score stays power × (1 + overlap).
4. **Rounding.** Grams use `round(x, 1)` after each edit (half-to-even). Lemonade at 40% is exactly 30.0 g, so that test still passes.
5. **Compensators can give a nutrient back.** `achieved_percent` is measured after repair. The “30% fat within 1 point” test will set `max_compensators` to 0 so it checks the cut itself.
6. **Hand-written calories.** Each ingredient must sit within 20% of 4×protein + 4×carbs + 9×fat. `tests/test_data.py` will catch misses.
7. **Do not rewrite `reformulate` in Phase 2.** New steps get their own tests. The old function stays until Phase 4, so the 25 tests stay green at every stop.

## Decisions

- A chemical group counts as one requested modification. Members get ids like `m2.sodium_benzoate_mg`.
- An unknown custom ingredient stays in the recipe, adds zeros, and raises `UNKNOWN_INGREDIENT`. It is never auto-replaced. A modification names an ingredient only if that name is in the recipe.
- Legacy goal `sugar` cuts the ingredient when the dish has it, otherwise nutrient `sugar_g`. `salt` / `sodium` cut ingredient `salt` or else chemical `sodium_mg`. `fat` cuts nutrient `fat_g`. An unknown legacy goal stays `MirageError` with code `INVALID_REQUEST`.
- Phase 2 `analyze` returns the internal baseline. Phase 5 shapes it for the detail route.
- Extra `list_dishes` fields (`display_name`, `servings`, `tags`, `badges`, `baseline`) land in Phase 5. Phases 2–4 only keep `dish`, `goals`, `ingredients`.
