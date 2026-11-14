# Phase 3 summary

Implemented taste.py (weighted repair, alternatives, taste and molecule scores) and warning_rules.py (structured warnings and per-serving badges), with focused tests. Every addition respects the safe cap, the shared 10% mass budget and the shared 25% targeted-metric giveback budget. Removed or user-edited foods cannot return.

Validation: pytest -q — 121 passed. Existing tests unchanged. Run `.venv/bin/pytest -q`. Check lemonade with a 60% sugar cut skips weak lemon zest and butter chicken fat cuts restore richness.

Decisions: safe caps are rounded down to a tenth before rounding the desired dose upward; giveback budgets are cumulative across additions. Remaining-deficit weights are recalculated after each addition. All taste effects remain estimates. The user authorized continuing through all phases, so no phase stop is required.
