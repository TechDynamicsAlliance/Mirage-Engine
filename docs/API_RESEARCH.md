# Foodoscope API integration research

Public documentation was researched on 2026-11-14, followed by authenticated live verification that day. The documentation sections below distinguish published examples from the actual response observations recorded at the end. Documentation examples alone are not proof of a successful live request.

## Authoritative sources

- [RecipeDB playground](https://www.foodoscope.com/playground/recipedb/)
- [FlavorDB playground](https://www.foodoscope.com/playground/flavordb/)
- [Public website JavaScript containing both Swagger 2.0 definitions](https://www.foodoscope.com/static/js/main.d53fa34d.js), retrieved from the script reference in the site's public HTML. This fingerprinted asset may change with future deployments.
- [FlavorDB FAQ and data model](https://cosylab.iiitd.edu.in/flavordb/faq)

The playground specifications declare HTTPS host `api.foodoscope.com`, base path `/`, and `Authorization: Bearer <API_KEY>`. Both playground request implementations add the Bearer prefix. No additional `x-api-key` header is required by these specifications. Keep credentials on the server.

## Recipe retrieval

All routes below are GET requests relative to `https://api.foodoscope.com`.

| Purpose | Route | Documented parameters |
| --- | --- | --- |
| Random recipe | `/recipe2-api/recipe/recipeofday` | None |
| Complete recipe | `/recipe2-api/search-recipe/{id}` | Recipe ID in path |
| Catalog | `/recipe2-api/recipe/recipesinfo` | `page`, `limit` |
| Title search | `/recipe2-api/recipe-bytitle/recipeByTitle` | `title` |
| Instructions | `/recipe2-api/instructions/{recipe_id}` | Recipe ID in path |
| Ingredient search | `/recipe2-api/recipebyingredient/by-ingredients-categories-title` | `includeIngredients`, `excludeIngredients`, `includeCategories`, `excludeCategories`, `title`, `page`, `limit` |
| Nutrition records | `/recipe2-api/recipe-nutri/nutritioninfo` | `page`, `limit` only |
| Recipe micronutrients | `/recipe2-api/recipe-micronutri/micronutritioninfo` | `page`, `limit` only |
| Ingredient/FlavorDB links | `/recipe2-api/connections/links` | At least one of `ingredient`, `entity`, `entity_id`; optional `page`, `size` |

The random endpoint example wraps metadata in `payload.data`. Metadata keys include `Recipe_id`, `Recipe_title`, `servings`, `Calories`, `Energy (kcal)`, `Protein (g)`, `Total lipid (fat) (g)`, and `Carbohydrate, by difference (g)`. Numeric values are commonly strings. `servings` may be text such as `36 crackers` or `2 quarts`, not a numeric count.

The detail endpoint example has sibling metadata and ingredient lists:

```json
{
  "success": true,
  "payload": {
    "data": {"Recipe_id": "2610", "Recipe_title": "Egyptian Lentil Soup", "servings": "4"},
    "ingredients": [
      {"ingredient": "lentil", "quantity": "1 cup"},
      {"ingredient": "tomato", "quantity": "1 large"}
    ]
  }
}
```

This is an excerpt of a documentation example, not a complete recipe fixture. The ingredient list must be read from the whole payload, not only from `payload.data`. Treat the detail schema as permissive and inspect live responses because examples can omit fields. The instructions response has `payload.recipe_id` and `payload.steps`.

## Ingredient nutrition limitations

The documented `nutritioninfo` example is a list of ingredient nutrient contributions identified by `Recipe_id` and USDA `ndb_id`. It repeats the same recipe ID for different NDB IDs. It supplies values such as `Sodium, Na (mg)`, `Energy (kcal)`, and `Total lipid (fat) (g)`, but the example has no ingredient name, gram mass, or explicit per-100g basis. These records must not be treated as generic ingredient profiles or divided evenly among ingredients. Matching requires an explicit ingredient-to-NDB mapping and documented quantity basis.

The micronutrient example is recipe-level data; it contains `Recipe_id` and totals for the recipe. Neither nutritional endpoint documents an ID filter: do not claim that adding `Recipe_id=...` selects one recipe without verifying actual behavior. Paginated scans should be bounded to avoid consuming many API calls.

`Calories` and `Energy (kcal)` are distinct in official examples: Egyptian Lentil Soup has values 196.0 and 805.6975 with four servings. Do not silently interchange them or assume either is per 100g. A nutrient cut needs ingredient-level nutrient density; where that cannot be established, report missing data instead of inventing a reduction.

Ingredient quantities such as `1 cup` or `1 large` also need ingredient-specific density/portion weights to become grams. Unrecognized volume, household-size, and free-text quantities should remain unresolved. An unknown value must not become zero or a fabricated 100 g quantity.

## FlavorDB flow

| Purpose | Route | Documented parameters |
| --- | --- | --- |
| Ingredient entity by name | `/flavordb/entities/by-entity-alias-readable` | `entity_alias_readable` |
| Ingredient entity by alias/category | `/flavordb/entities/by-name-and-category` | `entity_alias`, `category` |
| All ingredient molecules | `/flavordb/entities/by-id/{entityId}/molecules` | Integer entity ID in path |
| Compact molecule IDs/names | `/flavordb/entities/by-id/{entityId}/molecules-compact` | Integer entity ID in path |
| Molecule by name | `/flavordb/molecules_data/by-commonName` | `common_name` |
| Molecule by PubChem interval | `/flavordb/molecules_data/by-pubchemId-range` | `min`, `max` |
| Molecules by flavor descriptor | `/flavordb/molecules_data/by-flavorProfile` | `flavor_profile` |
| Ingredients containing a molecule | `/flavordb/molecules_data/by-id/{pubchemId}/entities` | Integer PubChem ID in path |
| Similar ingredient pairing | `/flavordb/food/by-alias` | `food_pair` |

Entity lookup returns identity/category/source information, not a molecule list. Follow the entity ID with the molecule route. The compact route explicitly returns an array of objects containing `pubchem_id` and `common_name`. The full molecule route is described as returning every flavor molecule in an ingredient, sorted rarest to most common; its schema reference points to `FnProperty`, which does not exactly match the `Molecule` model. Verify the actual response and support observed snake_case/camelCase field aliases rather than assuming the schema is perfect.

The `Molecule` definition includes `pubchemId`, `commonName`, `flavorProfile`, `femaFlavorProfile`, `taste`, and `odor`. Entity fields are camelCase in one schema but snake_case in connection examples, including `entity_id` and `entity_alias_readable`. Do not confuse the record's Mongo `_id` with the numeric entity ID or PubChem ID.

Use `/recipe2-api/connections/links?ingredient=<name>` for explicit cross-database mapping when available. Its `payload.data` rows contain `recipe`, `entity`, and `isLinked`; `recipe.flavordb_id` and `entity.entity_id` supply the association. The documented examples map `brown sugar` and `white sugar` to the Sugar entity 781. Prefer an exact linked ingredient row and retain the association as provenance.

FlavorDB establishes presence of flavor molecules, not their concentration per gram or sensory intensity. Molecule presence, common molecules, and mapped descriptors can support transparent heuristic similarity. They cannot justify a measured chemical dosage reduction or validated taste-equivalence claim. Missing profiles should be visible as incomplete coverage.

## Recommended live verification

1. Fetch one random recipe and then its detail by `Recipe_id`; preserve all raw responses locally without headers or credentials.
2. Resolve actual quantities and ingredient mappings, recording unresolved fields.
3. For an ingredient, fetch its linked FlavorDB entity and molecule list. Cache results to limit calls.
4. Run the same reformulation request through the public backend endpoint; assert targeted grams fall, protected ingredients stay unchanged, output is finite, and data-coverage warnings remain present.
5. For a nutrient cut, require verifiable ingredient-level nutrition and quantity basis. Otherwise assert a clear unavailable-data error. Do not treat a successful HTTP response as proof of a valid nutrient reformulation.
6. Record API route/status and recipe ID/title in a redacted smoke-test report. Label fixtures as fixtures and live responses as live evidence.

The public plan page advertises request limits and tokens, so cache repeated calls, bound retries, respect HTTP 429, and use a request budget for smoke tests. Do not acquire a subscription or regenerate credentials as part of testing.

## Authenticated findings (2026-11-14)

The actual `recipeofday` response selected **Coconut Rice, RecipeDB 54264**. Its detail endpoint returned HTTP 200 with `{success: true, data: {recipe, ingredients, instructions}}`, differing from the published example. The adapter supports both shapes. Eight ingredient rows contain household quantities; none supplies a verified gram weight. The imported record is saved in `data/live_data.json`.

`/recipe2-api/connections/links?ingredient=olive%20oil` returned an exact linked entity alongside substring results. Adding the documented optional `page` and `size` parameters returned HTTP 400 in the live probe, so the client omits them. It accepts only an exact ingredient match with `isLinked` and an entity ID. All eight ingredients in Coconut Rice were subsequently linked successfully; enrichment used 14 new requests and reused cached responses.

`/flavordb/entities/by-entity-alias-readable?entity_alias_readable=olive` returned a paginated object with a `content` list. `/flavordb/entities/by-id/307/molecules-compact` returned actual `{pubchem_id, common_name}` objects. The importer uses the explicit RecipeDB connection IDs to fetch those molecule lists, preserving the source identity in every profile.

The live nutrition endpoint accepted `page=1&limit=10`. Contrary to the abbreviated documentation example, records included `ingredientName`. They still lacked a verified gram basis; the first page contained a different recipe, 2610. Supplying `Recipe_id` as an extra filter returned HTTP 400. No whole-database scan was performed and those unrelated records were not assigned to Coconut Rice.

The user explicitly selected **RecipeDB and FlavorDB only**. No external nutrition dataset was imported. The live engine therefore preserves actual quantities and molecular identities, rejects unsupported nutrient/chemical reductions, and returns null for predicted nutrition and sensory scores. Demo fixtures are isolated behind an explicit mode and are never a fallback for failed live requests.

`python scripts/live_smoke.py` verifies the saved actual recipe through the public backend routes. It tests a 30% oil cut, stacked edits, removal, a legacy salt cut, determinism, unchanged input data, finite JSON, and the expected unsupported-nutrient error. It is a snapshot replay, not a new API availability test. The resulting evidence is in `docs/LIVE_TEST_REPORT.json` and `examples/live_*.json`.
