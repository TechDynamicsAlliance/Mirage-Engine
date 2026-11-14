# Phase 6 summary

Added units.py and POST /api/parse-recipe. parse_quantity reads fractions;
to_grams converts supported mass/volume/piece units; split_ingredient_line and
parse_ingredient_lines build a custom recipe with explicit unresolved lines.

Validation: `.venv/bin/pytest -q` — 164 passed. Check `2 tbsp butter` with an
ingredient-specific cup weight, and verify unsupported quantities are reported.
Decisions: solids require portion weights; liquids may use the specified 1 g/ml
assumption. Added ounces and pounds because actual RecipeDB recipes use them.
