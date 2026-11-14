"""Validate requests and apply v2 cuts; taste repair is the next phase."""

from __future__ import annotations

from copy import deepcopy

from catalog import MirageError, finite_number, resolve_name
from metrics import IMPLICIT_MAX_CUT, eligible_contributions, totals

MAX_MODIFICATIONS = 8
MET_TOLERANCE = 0.5  # Percentage points, allowing for rounding ingredient grams.


def parse_modifications(modifications: list | None, recipe: dict, data: dict) -> list[dict]:
    """Validate and canonicalize edits so all cuts refer to the same original recipe.

    A chemical group counts once toward the eight-request limit. Its present
    members become separate edits, in catalog order, with suffixed IDs.
    """
    if modifications is None:
        return []
    if not isinstance(modifications, list):
        raise MirageError("Modifications must be a list.", field="modifications")
    if len(modifications) > MAX_MODIFICATIONS:
        raise MirageError("Use at most 8 modifications.", "TOO_MANY_MODIFICATIONS", "modifications")
    original_totals = totals(recipe["ingredients"], data)
    parsed = []
    seen_targets = set()
    seen_ids = set()
    request_ids = set()
    for index, modification in enumerate(modifications):
        field = f"modifications[{index}]"
        if not isinstance(modification, dict):
            raise MirageError("Expected a modification object.", field=field)
        kind = modification.get("type")
        if kind not in ("ingredient", "nutrient", "chemical"):
            raise MirageError("Type must be ingredient, nutrient or chemical.", field=field + ".type")
        target = modification.get("target")
        if not isinstance(target, str) or not target.strip():
            raise MirageError("Target must be non-empty text.", field=field + ".target")
        target = target.strip()
        action = modification.get("action")
        if action not in ("reduce", "remove") or (action == "remove" and kind != "ingredient"):
            raise MirageError("Use reduce, or remove for an ingredient.", field=field + ".action")
        percent = None
        if action == "reduce":
            percent = finite_number(modification.get("percent"), field + ".percent", "PERCENT_OUT_OF_RANGE")
            maximum = 99 if kind == "ingredient" else 80
            if not 1 <= percent <= maximum:
                raise MirageError(f"Percent must be between 1 and {maximum}.",
                                  "PERCENT_OUT_OF_RANGE", field + ".percent")
        request_id = modification.get("id", f"m{index + 1}")
        if not isinstance(request_id, str) or not request_id.strip() or request_id in request_ids:
            raise MirageError("Modification IDs must be non-empty and unique.", field=field + ".id")
        request_ids.add(request_id)

        is_group = False
        if kind == "ingredient":
            target = resolve_name(target, data) or target
            if target not in recipe["ingredients"]:
                raise MirageError("That ingredient is not in the recipe.",
                                  "UNKNOWN_INGREDIENT_TARGET", field + ".target")
            info = data["ingredients"].get(target, {})
            targets = [{"id": target, "label": info.get("display_name", target), "unit": "g"}]
        else:
            group = "nutrients" if kind == "nutrient" else "chemicals"
            definitions = data["nutrient_defs" if kind == "nutrient" else "chemical_defs"]
            if kind == "chemical" and target in ("sodium", "salt"):
                target = "sodium_mg"
            targets = [item for item in definitions if item["id"] == target]
            if not targets and kind == "chemical":
                members = [item for item in definitions if item.get("group") == target]
                is_group = bool(members)
                targets = [item for item in members if original_totals[group][item["id"]] > 0]
            if not targets:
                code = "TARGET_NOT_PRESENT" if is_group else f"UNKNOWN_{kind.upper()}"
                raise MirageError(f"No present target named '{target}'.", code, field + ".target")
            for item in targets:
                if original_totals[group][item["id"]] <= 0:
                    raise MirageError(f"{item['label']} is not present in the original recipe.",
                                      "TARGET_NOT_PRESENT", field + ".target")

        for item in targets:
            key = (kind, item["id"])
            if key in seen_targets:
                raise MirageError("Each target may be changed only once.",
                                  "DUPLICATE_MODIFICATION", field + ".target")
            seen_targets.add(key)
            edit_id = f"{request_id}.{item['id']}" if is_group else request_id
            if edit_id in seen_ids:
                raise MirageError("Expanded modification IDs must be unique.", field=field + ".id")
            seen_ids.add(edit_id)
            parsed.append({"id": edit_id, "type": kind, "target": item["id"],
                           "action": action, "percent": percent,
                           "label": item["label"], "unit": item["unit"]})
    return parsed


def apply_ingredient_mods(recipe: dict, modifications: list[dict]) -> dict:
    """Apply explicit ingredient edits first and remember locks for later cuts and repair."""
    changed = deepcopy(recipe)
    touched = []
    results = []
    trace = []
    for edit in modifications:
        if edit["type"] != "ingredient":
            continue
        name = edit["target"]
        before = changed["ingredients"][name]
        if edit["action"] == "remove":
            after = 0.0
            del changed["ingredients"][name]
        else:
            after = round(before * (1 - edit["percent"] / 100), 1)
            changed["ingredients"][name] = after
        touched.append(name)
        results.append({"id": edit["id"], "status": "met", "note": None,
                        "affected_ingredients": [{"ingredient": name, "original_g": before, "new_g": after}]})
        trace.append({"phase": "modify", "text": f"{edit['id']}: {name} {before:g} g → {after:g} g ({edit['action']})."})
    return {"recipe": changed, "touched_ingredients": touched,
            "modification_results": results, "trace_detail": trace}


def apply_metric_mods(original_recipe: dict, recipe: dict, modifications: list[dict],
                      touched: list[str], data: dict) -> dict:
    """Cut eligible contributors proportionally, crediting earlier savings against the baseline."""
    changed = deepcopy(recipe)
    original_totals = totals(original_recipe["ingredients"], data)
    results = []
    trace = []
    for edit in modifications:
        if edit["type"] == "ingredient":
            continue
        group = "nutrients" if edit["type"] == "nutrient" else "chemicals"
        target = edit["target"]
        baseline = original_totals[group][target]
        current = totals(changed["ingredients"], data)[group][target]
        # Earlier edits may already have saved some or all of the requested amount.
        need = (edit["percent"] / 100) * baseline - (baseline - current)
        row = {"id": edit["id"], "status": "met", "note": None, "affected_ingredients": []}
        if need <= 0:
            row["status"] = "already_satisfied"
            row["note"] = "Earlier edits already reached this reduction."
        else:
            eligible = eligible_contributions(changed, edit["type"], target, baseline, touched, data)
            available = sum(eligible.values())
            if available == 0:
                row["status"] = "not_possible"
                row["note"] = ("No eligible contributors remain: core and structural ingredients, aromatics, "
                               "user-edited ingredients, and contributions below 5% are locked.")
            else:
                # The same fraction removes 'need' across all eligible contributors.
                fraction = min(need / available, IMPLICIT_MAX_CUT)
                if need / available > IMPLICIT_MAX_CUT:
                    row["status"] = "partial"
                    row["note"] = "The 80% automatic cut cap and locked contributors limit this reduction."
                for name in eligible:
                    before = changed["ingredients"][name]
                    after = round(before * (1 - fraction), 1)
                    changed["ingredients"][name] = after
                    row["affected_ingredients"].append({"ingredient": name, "original_g": before, "new_g": after})
                    trace.append({"phase": "modify", "text": (
                        f"{edit['id']}: {name} {before:g} g → {after:g} g to reduce {edit['label']}.")})
        if not row["affected_ingredients"]:
            trace.append({"phase": "modify", "text": f"{edit['id']}: {row['note']}"})
        results.append(row)
    return {"recipe": changed, "modification_results": results, "trace_detail": trace}


def finalize_modification_results(original_recipe: dict, final_recipe: dict, modifications: list[dict],
                                  results: list[dict], data: dict) -> list[dict]:
    """Recompute outcomes against the original dish; Phase 3 can call this again after repair.

    Keep internal amounts unrounded. The Phase 4 response builder will round
    them for display. 'already_satisfied' records the earlier no-op decision.
    """
    original = totals(original_recipe["ingredients"], data)
    final = totals(final_recipe["ingredients"], data)
    by_id = {row["id"]: deepcopy(row) for row in results}
    finalized = []
    for edit in modifications:
        row = by_id[edit["id"]]
        if edit["type"] == "ingredient":
            before = original_recipe["ingredients"][edit["target"]]
            after = final_recipe["ingredients"].get(edit["target"], 0.0)
        else:
            group = "nutrients" if edit["type"] == "nutrient" else "chemicals"
            before = original[group][edit["target"]]
            after = final[group][edit["target"]]
        # Divide before multiplying by 100 to avoid needless overflow on large amounts.
        achieved = (before - after) / before * 100
        requested = 100 if edit["action"] == "remove" else edit["percent"]
        if row["status"] != "already_satisfied":
            if achieved >= requested - MET_TOLERANCE:
                row["status"] = "met"
                row["note"] = None
            elif achieved > 0:
                row["status"] = "partial"
            else:
                row["status"] = "not_possible"
            if row["status"] in ("partial", "not_possible") and row["note"] is None:
                row["note"] = "Rounding ingredient grams or later changes limited the requested reduction."
        row.update({"type": edit["type"], "target": edit["target"], "label": edit["label"],
                    "action": edit["action"], "requested_percent": edit["percent"],
                    "achieved_percent": achieved, "unit": edit["unit"],
                    "original_amount": before, "new_amount": after})
        finalized.append(row)
    return finalized


def apply_modifications(recipe: dict, modifications: list | None, data: dict) -> dict:
    """Run steps 2–5 as a pure pipeline so they can be tested before taste repair is connected."""
    parsed = parse_modifications(modifications, recipe, data)
    ingredient_step = apply_ingredient_mods(recipe, parsed)
    metric_step = apply_metric_mods(recipe, ingredient_step["recipe"], parsed,
                                    ingredient_step["touched_ingredients"], data)
    results = finalize_modification_results(
        recipe, metric_step["recipe"], parsed,
        ingredient_step["modification_results"] + metric_step["modification_results"], data)
    warnings = [
        {"code": "PARTIAL_MODIFICATION", "severity": "caution",
         "message": f"{row['label']}: {row['note']}", "related": [row["id"], row["target"]]}
        for row in results if row["status"] in ("partial", "not_possible")
    ]
    return {"recipe": metric_step["recipe"], "modifications": parsed,
            "touched_ingredients": ingredient_step["touched_ingredients"],
            "modification_results": results, "warning_details": warnings,
            "warnings": [warning["message"] for warning in warnings],
            "trace_detail": ingredient_step["trace_detail"] + metric_step["trace_detail"]}
