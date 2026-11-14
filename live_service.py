"""Use actual RecipeDB quantities and FlavorDB identities without inventing missing measurements."""
from copy import deepcopy
import math
import re

from catalog import DishNotFound, MirageError, finite_number, resolve_recipe
from foodoscope_client import unwrap
from recipe_adapter import recipe_payload
from units import parse_quantity, split_ingredient_line, to_grams, UNIT_ALIASES, MASS_G, VOLUME_ML
from engine import normalize_options
from modify import parse_modifications

SOURCE_METRICS = {
    "calories_kcal": "Energy (kcal)", "fat_g": "Total lipid (fat) (g)",
    "saturated_fat_g": "Fatty acids, total saturated (g)", "carbs_g": "Carbohydrate, by difference (g)",
    "sugar_g": "Sugars, total (g)", "fiber_g": "Fiber, total dietary (g)",
    "protein_g": "Protein (g)", "cholesterol_mg": "Cholesterol (mg)",
    "sodium_mg": "Sodium, Na (mg)", "caffeine_mg": "Caffeine (mg)",
}


def resolve_live_source(source, data):
    """Resolve saved source records or user gram inputs without inventing measurements."""
    if isinstance(source, str):
        if source not in data["dishes"]:
            raise DishNotFound(f"Dish '{source}' not found.")
        return deepcopy(data["dishes"][source])
    recipe = resolve_recipe(source, data)
    return {"payload": {"recipe": {"Recipe_id": "custom", "Recipe_title": recipe["name"],
                                   "servings": str(recipe["servings"]), "Source": "user"},
                        "ingredients": [{"ingredient": name, "quantity": grams, "unit": "g",
                                         "M_or_A": "M" if name in recipe["core_ingredients"] else "A"}
                                        for name, grams in recipe["ingredients"].items()]},
            "flavor_profiles": {}, "source_issues": [], "tags": recipe["tags"],
            "unresolved_ingredients": recipe["unresolved_ingredients"]}


def _rows(payload):
    """Accept the observed RecipeDB arrays and FlavorDB paginated content wrappers."""
    value = unwrap(payload)
    if isinstance(value, dict):
        value = value.get("content", value.get("items", []))
    return value if isinstance(value, list) else []


def _number(value):
    """Return only finite nonnegative source numbers, keeping missing values distinct from zero."""
    try:
        if value is None or isinstance(value, bool):
            return None
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def ingredient_rows(payload):
    """Preserve upstream quantities in their own units; only known mass units yield grams."""
    body = recipe_payload(payload)
    rows = []
    used = set()
    for index, item in enumerate(body["ingredients"]):
        label = str(item.get("ingredient", "")).strip()
        if not label:
            raise MirageError("RecipeDB omitted an ingredient name.", "UPSTREAM_INVALID_RESPONSE", "ingredients")
        name = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or f"ingredient_{index + 1}"
        if name in used:
            name += f"_{index + 1}"
        used.add(name)
        quantity, unit = None, str(item.get("unit", "")).strip().lower()
        unit = UNIT_ALIASES.get(unit, unit)
        try:
            quantity = parse_quantity(item.get("quantity"))
            if unit not in (*MASS_G, *VOLUME_ML, "piece"):
                raise MirageError("Unrecognized unit.")
        except MirageError:
            try:
                parsed, parsed_unit, _ = split_ingredient_line(item.get("ingredient_Phrase", "") or f"{item.get('quantity', '')} {label}")
                quantity = parse_quantity(parsed)
                unit = UNIT_ALIASES.get(parsed_unit.lower(), parsed_unit.lower())
            except MirageError:
                quantity = None
        grams = None
        if quantity is not None and unit in MASS_G:
            grams = to_grams(quantity, unit)
        if _number(item.get("grams")) is not None and _number(item.get("grams")) > 0:
            grams = _number(item["grams"])
        rows.append({"name": name, "display_name": label, "quantity": quantity, "unit": unit or None,
                     "grams": grams, "is_core": item.get("M_or_A") == "M",
                     "role": "structural" if item.get("M_or_A") == "M" else "unknown",
                     "source_phrase": item.get("ingredient_Phrase"), "source_ingredient": deepcopy(item),
                     "nutrients": {}, "chemicals": {}})
    if not 1 <= len(rows) <= 40:
        raise MirageError("Imported recipes must contain 1 to 40 ingredients.", "INVALID_RECIPE", "ingredients")
    return rows


def enrich_recipe(payload, client):
    """Resolve exact cross-database links and fetch real molecule IDs, recording incomplete coverage."""
    profiles, issues = {}, []
    for row in ingredient_rows(payload):
        name = row["name"]
        try:
            links = _rows(client.links(row["display_name"]))
            link = next((item for item in links if item.get("recipe", {}).get("ingredient", "").casefold() == row["display_name"].casefold()
                         and item.get("isLinked") and item.get("entity")), None)
            if link is None:
                issues.append({"ingredient": name, "reason": "No exact linked FlavorDB entity."})
                continue
            entity_id = link["entity"].get("entity_id", link["recipe"].get("flavordb_id"))
            molecules = _rows(client.molecules(entity_id))
            profiles[name] = {"entity_id": entity_id, "entity_name": link["entity"].get("entity_alias_readable"),
                              "mapping": "exact_recipe_ingredient_link", "molecules": [
                                  {"pubchem_id": str(item.get("pubchem_id", item.get("pubchemId"))),
                                   "common_name": item.get("common_name", item.get("commonName"))}
                                  for item in molecules if item.get("pubchem_id", item.get("pubchemId")) is not None]}
        except MirageError as error:
            if error.code in ("UPSTREAM_AUTH_ERROR", "API_NOT_CONFIGURED"):
                raise
            issues.append({"ingredient": name, "reason": error.code})
    return {"payload": deepcopy(payload), "flavor_profiles": profiles, "source_issues": issues}


def analyze_live(record: dict, definitions: dict) -> dict:
    """Show source nutrition and quantities honestly, including data needed before metric cuts."""
    body = recipe_payload(record["payload"])
    source = body["recipe"]
    user_source = source.get("Source") == "user"
    data_source = "user" if user_source else "recipedb+flavordb"
    rows = ingredient_rows(record["payload"])
    raw_servings = str(source.get("servings", ""))
    servings = _number(raw_servings) if re.fullmatch(r"\d+(?:\.\d+)?", raw_servings) else None
    servings = servings if servings is not None and servings >= 1 else 1
    notes = ["RecipeDB ingredient nutrient densities and FlavorDB taste intensities are unavailable. Nutrient cuts and taste repair require those measurements.",
             "Household quantities are retained in their original units; missing gram weights are null.",
             "FlavorDB identifies molecules, not their concentration, safety dose or sensory intensity."]
    if str(servings) not in (raw_servings, raw_servings + ".0"):
        notes.append(f"Yield '{raw_servings}' is not a numeric serving count; one serving means the whole recipe.")
    reported = {group: {item["id"]: _number(source.get(SOURCE_METRICS.get(item["id"], ""))) for item in definitions[key]}
                for group, key in (("nutrients", "nutrient_defs"), ("chemicals", "chemical_defs"))}
    profiles = record.get("flavor_profiles", {})
    for row in rows:
        row["flavor_profile"] = deepcopy(profiles.get(row["name"]))
    missing_grams = [row["name"] for row in rows if row["grams"] is None]
    missing_flavor = [row["name"] for row in rows if row["name"] not in profiles]
    warning = {"code": "SOURCE_DATA_INCOMPLETE", "severity": "caution", "message": notes[0], "related": [row["name"] for row in rows]}
    unknown_warnings = [{"code": "UNKNOWN_INGREDIENT", "severity": "caution",
                         "message": f"Unknown ingredient '{item['name']}': its nutrition is unavailable.", "related": [item["name"]]}
                        for item in record.get("unresolved_ingredients", [])]
    warnings = [warning, *unknown_warnings]
    return {"schema_version": 2, "dish": source["Recipe_title"] if user_source else "recipedb_" + str(source["Recipe_id"]), "recipe_id": None if user_source else str(source["Recipe_id"]),
            "display_name": source.get("Recipe_title", "Imported recipe"), "servings": servings, "tags": deepcopy(record.get("tags", [])), "ingredients": rows,
            "totals": reported, "per_serving": {group: {key: round(amount / servings, 2) if amount is not None else None for key, amount in values.items()}
                                               for group, values in reported.items()},
            "dv_pct": {group: {item["id"]: round(reported[group][item["id"]] / servings / item["daily_value"] * 100, 1)
                                if item.get("daily_value") and reported[group][item["id"]] is not None else None for item in definitions[key]}
                       for group, key in (("nutrients", "nutrient_defs"), ("chemicals", "chemical_defs"))},
            "badges": [], "modifiable": {"ingredients": [{key: row[key] for key in ("name", "display_name", "quantity", "unit", "grams", "role", "is_core")}
                                                           | {"can_reduce": row["quantity"] is not None, "can_remove": True, "max_percent": 99,
                                                              "note": "Edit uses the reported unit; quantitative nutrition and taste effects are unavailable."} for row in rows],
                                           "nutrients": [], "chemicals": []},
            "unresolved_ingredients": deepcopy(record.get("unresolved_ingredients", [])), "warning_details": warnings, "warnings": [item["message"] for item in warnings],
            "data_source": data_source, "data_quality": {"data_source": data_source, "placeholder_values": False,
                "unknown_ingredients": deepcopy(record.get("unresolved_ingredients", [])), "notes": notes, "missing_gram_weights": missing_grams, "missing_flavor_profiles": missing_flavor,
                "nutrition_basis": "unavailable" if user_source else "recipe_level_values_as_reported_by_RecipeDB", "ingredient_nutrition_available": False,
                "quantitative_taste_available": False, "source_issues": deepcopy(record.get("source_issues", []))},
            "source_metadata": {"recipe_id": None if user_source else str(source["Recipe_id"]), "recipe_url": source.get("url"), "source": source.get("Source"),
                                "region": source.get("Region"), "sub_region": source.get("Sub_region"),
                                "prep_minutes": _number(source.get("prep_time")), "cook_minutes": _number(source.get("cook_time")),
                                "total_minutes": _number(source.get("total_time")), "listed_calories": _number(source.get("Calories")),
                                "instructions": [item.get("steps", "") for item in body.get("instructions", []) if item.get("steps")],
                                "recipedb_endpoint": None if user_source else f"https://api.foodoscope.com/recipe2-api/search-recipe/{source['Recipe_id']}"}}


def reformulate_live(record: dict, modifications, options, definitions: dict, *, goal=None, reduce_percent=None):
    """Apply real ingredient edits in reported units without fabricating nutrient savings or taste retention."""
    detail = analyze_live(record, definitions)
    rows = {row["name"]: row for row in detail["ingredients"]}
    aliases = {row["display_name"].casefold(): name for name, row in rows.items()}
    if goal is not None:
        if modifications is not None:
            raise MirageError("Use legacy goals or modifications, not both.", field="modifications")
        if goal not in ("sugar", "salt", "sodium", "fat"):
            raise MirageError("Unknown legacy goal.", field="goal")
        percent = finite_number(reduce_percent, "reduce_percent", "PERCENT_OUT_OF_RANGE")
        if not 1 <= percent <= 80:
            raise MirageError("Legacy reduction must be 1 to 80 percent.", "PERCENT_OUT_OF_RANGE", "reduce_percent")
        target = "salt" if goal == "sodium" else goal
        if target not in rows:
            raise MirageError("Ingredient nutrient densities are needed for that legacy goal.", "DATA_UNAVAILABLE", "goal")
        modifications = [{"type": "ingredient", "target": target, "action": "reduce", "percent": percent}]
    elif reduce_percent is not None:
        raise MirageError("A legacy percentage requires a goal.", field="goal")
    modifications = deepcopy(modifications) if modifications is not None else []
    if not isinstance(modifications, list):
        raise MirageError("Modifications must be a list.", field="modifications")
    if len(modifications) > 8:
        raise MirageError("Use at most 8 modifications.", "TOO_MANY_MODIFICATIONS", "modifications")
    for index, edit in enumerate(modifications):
        if not isinstance(edit, dict):
            raise MirageError("Expected an edit object.", field=f"modifications[{index}]")
        if edit.get("type") in ("nutrient", "chemical"):
            kind = edit["type"]
            target = edit.get("target")
            valid = {item["id"] for item in definitions["nutrient_defs" if kind == "nutrient" else "chemical_defs"]}
            if kind == "chemical":
                valid.update(("sodium", "salt", "preservatives"))
            if not isinstance(target, str) or target not in valid:
                raise MirageError("Unknown metric.", f"UNKNOWN_{kind.upper()}", f"modifications[{index}].target")
            raise MirageError("RecipeDB does not provide verified ingredient nutrient densities for this recipe; use an ingredient edit instead.",
                              "DATA_UNAVAILABLE", f"modifications[{index}].target")
        if isinstance(edit.get("target"), str):
            edit["target"] = aliases.get(edit["target"].casefold(), edit["target"])
    # This validation-only catalog carries no invented density. Native-unit math below is separate.
    validator_data = {**definitions, "ingredients": {name: {"display_name": row["display_name"], "aliases": []} for name, row in rows.items()}}
    validator_recipe = {"ingredients": {name: 1 for name in rows}, "servings": detail["servings"]}
    edits = parse_modifications(modifications, validator_recipe, validator_data)
    opts = normalize_options(options, validator_recipe)
    original = deepcopy(rows)
    results, trace = [], [{"phase": "baseline", "text": "Using original RecipeDB quantities; no per-gram nutrition or taste strengths were supplied."}]
    for edit in edits:
        name = edit["target"]
        row = rows[name]
        old = row["quantity"]
        if edit["action"] == "remove":
            new, fraction = 0, 0
        else:
            if old is None:
                raise MirageError("Correct the source quantity before reducing this ingredient.", "MISSING_QUANTITY_DATA", f"ingredients.{name}")
            fraction = 1 - edit["percent"] / 100
            new = old * fraction
        new_g = round(row["grams"] * fraction, 1) if row["grams"] is not None else None
        results.append({"id": edit["id"], "type": "ingredient", "target": name, "label": row["display_name"], "action": edit["action"],
                        "requested_percent": edit["percent"], "achieved_percent": 100 if edit["action"] == "remove" else edit["percent"],
                        "status": "met", "unit": row["unit"], "original_amount": old, "new_amount": round(new, 6),
                        "amount_basis": "reported_unit", "affected_ingredients": [{"ingredient": name, "original_g": row["grams"], "new_g": new_g}],
                        "note": "Only the reported ingredient quantity is changed; nutrient and sensory changes are unknown."})
        trace.append({"phase": "modify", "text": f"{edit['id']}: {row['display_name']} {old} → {new:g} {row['unit'] or 'reported units'}."})
        if edit["action"] == "remove":
            del rows[name]
        else:
            row["quantity"], row["grams"] = new, new_g
    by_target = {row["target"]: row for row in results}
    changes = []
    warnings = deepcopy(detail["warning_details"])
    for name, row in original.items():
        after = rows.get(name)
        result = by_target.get(name)
        new_g = after["grams"] if after else (0 if row["grams"] is not None else None)
        changes.append({"ingredient": name, "display_name": row["display_name"], "role": row["role"],
                        "status": "removed" if after is None else "reduced" if result else "unchanged",
                        "original_g": row["grams"], "new_g": new_g,
                        "delta_g": new_g - row["grams"] if new_g is not None and row["grams"] is not None else None,
                        "delta_pct": -result["achieved_percent"] if result else 0, "is_compensator": False,
                        "reason": "You requested this ingredient change." if result else "Kept at its original amount.",
                        "modification_ids": [result["id"]] if result else [], "unit": row["unit"],
                        "original_quantity": row["quantity"], "new_quantity": round(after["quantity"], 6) if after and after["quantity"] is not None else 0 if after is None else None})
        if result and row["is_core"] and result["achieved_percent"] > 30:
            warnings.append({"code": "CORE_INGREDIENT_CHANGED", "severity": "warning", "message": f"Changing {row['display_name']} this much changes the identity of the dish.", "related": [name]})
    original_molecules = {m["pubchem_id"] for row in original.values() for m in (row.get("flavor_profile") or {}).get("molecules", [])}
    final_molecules = {m["pubchem_id"] for row in rows.values() for m in (row.get("flavor_profile") or {}).get("molecules", [])}
    coverage_complete = not detail["data_quality"]["missing_flavor_profiles"]
    preserved = len(original_molecules & final_molecules) / len(original_molecules) * 100 if original_molecules else None
    scores = {"taste_retention_pct": None, "target_reached": None, "flavor_preserved_pct": round(preserved, 1) if coverage_complete and preserved is not None else None,
              "by_axis": {axis: None for axis in definitions["taste_axes"]}}
    trace.append({"phase": "score", "text": "Quantitative taste retention is unavailable; molecule presence does not measure taste intensity."})
    if not opts["include_trace"]:
        trace = []
    def recipe_view(items):
        """Keep gram fields null when unknown and expose original-unit amounts separately."""
        return {"ingredients": {name: row["grams"] for name, row in items.items()}, "tags": deepcopy(detail["tags"]),
                "quantities": {name: {"amount": round(row["quantity"], 6) if row["quantity"] is not None else None,
                                      "unit": row["unit"]} for name, row in items.items()}}
    return {"schema_version": 2, "analysis_status": "source_data_incomplete", "dish": detail["dish"], "recipe_id": detail["recipe_id"],
            "recipe_name": detail["display_name"], "servings": opts["servings"], "goal": goal, "reduce_percent": reduce_percent,
            "original_recipe": recipe_view(original), "new_recipe": recipe_view(rows), "added_compensators": [], "scores": scores,
            "new_flavor_notes": sorted(final_molecules - original_molecules), "lost_flavor_notes": sorted(original_molecules - final_molecules),
            "flavor_note_identifier": "pubchem_id", "modification_results": results, "ingredient_changes": changes,
            "nutrient_comparison": [], "chemical_comparison": [],
            "nutrition": {"original": {"sugar_g": detail["totals"]["nutrients"].get("sugar_g"),
                                        "sodium_mg": detail["totals"]["chemicals"].get("sodium_mg"), "fat_g": detail["totals"]["nutrients"].get("fat_g")},
                          "reformulated": {"sugar_g": None, "sodium_mg": None, "fat_g": None}, "sugar_saved_g": None, "sodium_saved_mg": None, "fat_saved_g": None},
            "reported_original_totals": deepcopy(detail["totals"]), "taste_profile": {"axes": [{"axis": axis, "label": axis.title(), "original": None,
                "after_cut": None, "final": None, "retention_pct": None, "affected": None} for axis in definitions["taste_axes"]], "affected_axes": []},
            "headline": {"summary_text": f"Applied {len(results)} ingredient edits in their reported units. Nutrition savings and taste retention are unavailable.", "key_metrics": []},
            "warning_details": warnings, "warnings": [row["message"] for row in warnings], "badges": {"original": [], "reformulated": []},
            "trace_detail": trace, "trace": [row["text"] for row in trace], "data_source": detail["data_source"], "data_quality": deepcopy(detail["data_quality"]),
            "source_metadata": detail["source_metadata"], "options_used": opts}
