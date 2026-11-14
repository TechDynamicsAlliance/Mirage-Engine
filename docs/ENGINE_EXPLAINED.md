# How MIRAGE changes a recipe

This walkthrough describes the complete quantitative engine exercised by the labelled demo fixtures. The default API uses real RecipeDB/FlavorDB records: ingredient edits work in reported units, while missing nutrient densities and taste strengths disable the corresponding calculations. See the README for those source-data limits.

1. **Resolve the recipe.** A saved dish is copied, or custom ingredient names are
   matched by exact name, alias and simple normalization. Misspellings stay visible
   with suggestions; a fuzzy guess is never silently accepted.
2. **Validate the edits.** Ingredient, nutrient and chemical edits have different
   percentage limits. Duplicate targets are rejected. A preservative-group request
   expands into the preservative chemicals actually present.
3. **Measure the original.** Grams times each per-gram value gives nutrition and
   four modelled tastes. Molecule identities form the flavor fingerprint.
4. **Apply explicit ingredient edits.** Remove or reduce exactly what the user
   requested, then lock those foods so automatic changes cannot undo the request.
5. **Apply metric cuts.** Count savings from earlier edits. Cut eligible contributors
   by the same fraction; cores, structural ingredients and aromatics stay locked.
   Each automatic cut is capped at 80% and each contributor must represent at least
   5% of the original metric. An impossible request gets an explanatory result.
6. **Repair taste.** For axes below 95% retention, rank compatible compensators by
   weighted taste power and molecular overlap. Respect each safe cap, a shared
   10% mass limit and a shared 25% targeted-nutrient giveback budget. Skip additions
   that recover less than one percentage point of an affected taste axis.
7. **Compare the final recipe.** Recalculate nutrition after additions. Report
   signed changes, portions, ingredient explanations, warnings and the weakest
   affected taste retention. Percent change from a zero baseline is null.

## Worked offline lemonade example

The labelled demo has 50 g sugar, 100 g lemon juice and 500 g water, serving four.
Its modelled sweetness is 52.5 units. A 20% ingredient sugar cut leaves 40 g sugar
and sweetness of 42.5. The 95% target is 49.875, so the deficit is 7.375.
Vanilla ranks first and adds 3 g, its cap, restoring 6 taste units. Mint then adds
2.8 g, restoring 1.4 units. Final modelled sweetness is 49.9, or about 95.0%.
The result includes all changed nutrients, including small side effects from those
additions. This example explains the algorithm, not a validated taste experiment.

All calculations remain unrounded until output, except edited ingredient grams
which are rounded to 0.1 g. Display totals use two decimals and percentages one.
