# Phase 5 summary

Added detail.py, schemas.py and the full main.py endpoints, standardized exception
handlers, API tests, example generator, README and engine walkthrough.
build_detail supplies portions and feasible slider limits; schema validators
enforce one source; route functions delegate calculations to the engine.
The example generator runs real calculations against labelled offline fixtures.

Run `.venv/bin/pytest -q`, `python scripts/dump_examples.py`, and
`uvicorn main:app --reload`; inspect `/docs` and the generated examples.
Validation before documentation generation: 157 passed. The Phase 2 precision
test was updated to expect rounded public analysis (0.12), while still asserting
unrounded internal math (0.12345). All original 25 tests remain unchanged.

Decisions: retain the original health payload and CORS policy. Framework errors
use the same error envelope. Unknown ingredients remain visible in detail.
