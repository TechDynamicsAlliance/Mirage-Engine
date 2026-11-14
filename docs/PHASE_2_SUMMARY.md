# Phase 2 summary

The repository already contained Phases 0–1. Its starting test run passed all
38 tests. Phase 2 now implements recipe resolution, baseline analysis, and cuts
(algorithm steps 1–5). The existing reformulation API still uses its original
flow, as the saved plan requires until Phase 4.

## Files and functions

- **catalog.py** (new):
  - `load_data`: reads a fresh copy of the local JSON; moved from engine.py and still importable there.
  - `finite_number`: rejects non-numbers, booleans, NaN, infinity and numeric overflow.
  - `normalize_name`: handles case, spaces, hyphens and a simple trailing plural “s”.
  - `resolve_name`: tries exact names, aliases and normalized names, in that order.
  - `suggest_names`: returns up to three close catalog names without accepting them automatically.
  - `resolve_recipe`: validates and copies dishes/custom recipes, combines repeated ingredient names, resolves cores and records unknown foods.
  - `_text` and `_text_list`: validate recipe text and lists, with useful error field paths.
  - `MirageError.__init__` and `DishNotFound.__init__`: attach error codes and fields while preserving the existing exception types.
- **metrics.py** (new):
  - `contributions`: measures every ingredient's nutrient and chemical amounts.
  - `totals`: sums those amounts without rounding.
  - `per_serving`: divides totals by the validated serving count.
  - `taste_vector`: measures sweetness, saltiness, umami and richness.
  - `fingerprint`: returns the sorted union of molecules from ingredients with positive grams.
  - `eligible_contributions`: finds contributors meeting the 5% threshold, excluding cores, structural foods, aromatics and explicit user edits.
- **modify.py** (new):
  - `parse_modifications`: checks targets, actions, percentages, duplicates and limits; expands chemical groups and assigns IDs.
  - `apply_ingredient_mods`: applies ingredient requests first and records which ingredients are locked.
  - `apply_metric_mods`: applies nutrient/chemical requests in order, credits earlier savings and caps each automatic cut at 80%.
  - `finalize_modification_results`: calculates achieved reductions against the original dish; it can run again after taste repair is added.
  - `apply_modifications`: connects the cut steps and returns the changed recipe, outcomes, partial-cut warnings and modification trace.
- **engine.py** (changed): `analyze` exposes the internal baseline, unknown-ingredient warnings and suggestions. Shared errors and loading are re-exported from catalog.py.
- **tests/test_modify.py** (new): 59 test cases cover the above behavior, including deterministic results and unchanged input data. Its `data`, `edit` and `run` helpers load fixtures, construct requests and run the cut pipeline.
- **docs/PHASE_2_SUMMARY.md** (new): this handoff.

## How to run and what to check

From the repository directory:

```sh
source .venv/bin/activate
pytest -q
python - <<'PY'
from engine import analyze, load_data
from modify import apply_modifications

data = load_data()
baseline = analyze("butter_chicken", data)
result = apply_modifications(baseline["recipe"], [
    {"type": "nutrient", "target": "fat_g", "action": "reduce", "percent": 30}
], data)
print(result["modification_results"])
PY
```

The example should report `met`: fat falls from approximately 143.03 g to
100.09 g across the dish, a 30.0% reduction. Chicken and aromatic ingredients
stay unchanged. These are placeholder estimates and this example includes no
taste repair yet. Try a custom ingredient named `sugra` with `analyze`: it should
stay unresolved, suggest `sugar`, and contribute zero nutrition.

Validation: **97 passed in 0.19 seconds**. All 25 original engine tests and all
13 data tests pass unchanged. New modules also parse as Python 3.10 syntax and
every new function has a docstring. No network or MCP tools were used; `.env`
was neither read nor created.

## Decisions I made

- Followed the existing plan's phase boundary: `analyze` returns an internal,
  unrounded baseline for now. Public v2 reformulation/output integration belongs
  to Phase 4 and the endpoint/detail contract to Phase 5.
- Repeated custom ingredient names and aliases are combined, preserving first
  appearance. The 40-ingredient limit applies to submitted rows before combining.
- Omitting custom cores defaults to structural foods; an explicit empty core list
  remains empty. Structural roles are still protected from automatic cuts.
- Unknown foods can be explicitly reduced or removed when they are in the recipe.
- A chemical group counts as one submitted request; duplicate targets are checked
  after expansion. Explicit IDs must be unique. `remove` ignores an optional
  percent and records its requested percentage as null.
- Error definitions live in catalog.py to avoid a circular import or another file.
- Kept Phase 1's catalog validation tests; a duplicate runtime catalog validator
  was unnecessary for this local prototype. Search, daily-reference formatting,
  badges and the complete warning rules remain with their later phases.

Stopped after Phase 2. Next authorized continuation: Phase 3, taste repair,
scoring and warning rules.
