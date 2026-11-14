# Phase 4 summary

Added compare.py and connected engine.reformulate to the v2 pipeline. The response
now includes final modification outcomes, ingredient explanations, all metric
comparisons, portions, headlines, structured warnings, provenance and trace.
Legacy positional and keyword requests retain all response keys; all three
legacy nutrient-saving fields are now always present.

Functions: normalize_options validates limits; reformulate coordinates cuts and
repair; comparison_rows measures changes; ingredient_changes explains them;
build_headline selects four metrics; data_quality reports sources; build_response
assembles the response. Formatting helpers only round output.

Validation: `.venv/bin/pytest -q` — 143 passed, including every present nutrient
and chemical at 10/30/50/80% plus one stacked request per dish, under five seconds.
Original 25 tests unchanged. Check `trace` matches `trace_detail` and final
achieved percentages include compensators. Decisions: preserve stable catalog
order to break ties; no percent change is defined for a zero baseline.
