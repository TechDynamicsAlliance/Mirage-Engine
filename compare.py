"""Build frontend-ready comparisons from the unrounded reformulation pipeline."""

from __future__ import annotations

from copy import deepcopy
import math

from catalog import MirageError
from metrics import contributions, totals
from modify import finalize_modification_results
from warning_rules import badges, build_warnings

CHANGE_TOLERANCE_PERCENT = 0.5
HEADLINE_METRIC_LIMIT = 4


def _rounded(value: float | None, places: int = 2) -> float | None:
    """Round only public output and reject overflow instead of emitting invalid JSON."""
    if value is None:
        return None
    if not math.isfinite(value):
        raise MirageError("Recipe amounts are too large to compare safely.",
                          "INVALID_RECIPE", "custom_recipe.ingredients")
    result = round(value, places)
    return 0.0 if result == 0 else result


def _percent_change(before: float, after: float) -> float | None:
    """Represent change as new minus old; a zero baseline has no defined percentage."""
    return (after - before) / before * 100 if before else None


def _display_name(name: str, data: dict) -> str:
    """Use a catalog label when available while preserving unmatched ingredient names."""
    return data["ingredients"].get(name, {}).get("display_name", name)


def _change_type(before: float, after: float, direction: str) -> str:
    """Classify the unrounded change, allowing half a percent of baseline for noise."""
    if abs(after - before) <= abs(before) * CHANGE_TOLERANCE_PERCENT / 100:
        return "unchanged"
    improved = after < before if direction == "lower_is_better" else after > before
    return "improved" if improved else "worsened"


def comparison_rows(original_recipe: dict, final_recipe: dict, modifications: list[dict],
                    servings: float, data: dict) -> dict:
    """Calculate totals, portions and contributors together so the UI needs no math."""
    before = totals(original_recipe["ingredients"], data)
    after = totals(final_recipe["ingredients"], data)
    original_contributions = contributions(original_recipe["ingredients"], data)
    final_contributions = contributions(final_recipe["ingredients"], data)
    ingredient_order = list(dict.fromkeys([
        *original_recipe["ingredients"], *final_recipe["ingredients"],
    ]))
    targeted = {(edit["type"], edit["target"]) for edit in modifications}
    result = {"nutrient_comparison": [], "chemical_comparison": []}
    for kind, group, definitions in (
        ("nutrient", "nutrients", "nutrient_defs"),
        ("chemical", "chemicals", "chemical_defs"),
    ):
        for definition in data[definitions]:
            metric = definition["id"]
            old, new = before[group][metric], after[group][metric]
            if old <= 0 and new <= 0:
                continue
            original_by_ingredient = original_contributions[group][metric]
            final_by_ingredient = final_contributions[group][metric]
            # Sort the original unrounded amounts, with recipe order breaking ties.
            ordered = sorted(ingredient_order,
                             key=lambda name: original_by_ingredient.get(name, 0), reverse=True)
            by_ingredient = []
            for name in ordered:
                old_amount = original_by_ingredient.get(name, 0.0)
                new_amount = final_by_ingredient.get(name, 0.0)
                if old_amount == 0 and new_amount == 0:
                    continue
                by_ingredient.append({
                    "ingredient": name, "display_name": _display_name(name, data),
                    "original_amount": _rounded(old_amount),
                    "new_amount": _rounded(new_amount),
                    "delta_amount": _rounded(new_amount - old_amount),
                })
            reference = definition.get("daily_value")
            result[f"{kind}_comparison"].append({
                "id": metric, "label": definition["label"], "unit": definition["unit"],
                "direction": definition["direction"],
                "original_total": _rounded(old), "new_total": _rounded(new),
                "delta_total": _rounded(new - old),
                "original_per_serving": _rounded(old / servings),
                "new_per_serving": _rounded(new / servings),
                "delta_per_serving": _rounded((new - old) / servings),
                "delta_pct": _rounded(_percent_change(old, new), 1),
                "change_type": _change_type(old, new, definition["direction"]),
                "original_dv_pct": _rounded(old / servings / reference * 100, 1) if reference else None,
                "new_dv_pct": _rounded(new / servings / reference * 100, 1) if reference else None,
                "targeted": (kind, metric) in targeted,
                "by_ingredient": by_ingredient,
            })
    return result


def ingredient_changes(original_recipe: dict, final_recipe: dict, results: list[dict],
                       compensators: list[dict], data: dict) -> list[dict]:
    """Explain each ingredient change in original order and connect it to requested edits."""
    order = list(dict.fromkeys([*original_recipe["ingredients"], *final_recipe["ingredients"]]))
    added = {item["ingredient"]: item for item in compensators}
    rows = []
    for name in order:
        before = original_recipe["ingredients"].get(name, 0.0)
        after = final_recipe["ingredients"].get(name, 0.0)
        edits = [result for result in results
                 if any(item["ingredient"] == name for item in result["affected_ingredients"])]
        if name not in original_recipe["ingredients"]:
            status = "added"
        elif after <= 0 < before:
            status = "removed"
        elif after < before:
            status = "reduced"
        else:
            status = "unchanged"
        if name in added:
            item = added[name]
            mechanism = data.get("mechanisms", {}).get(item.get("mechanism"), {})
            label = mechanism.get("label", str(item.get("mechanism", "taste repair")).replace("_", " "))
            reason = f"Added to restore {item['axis']} taste ({label.lower()})."
        elif edits:
            descriptions = []
            for edit in edits:
                if edit["type"] == "ingredient":
                    description = (f"You asked to remove {_display_name(name, data)}."
                                   if edit["action"] == "remove" else
                                   f"You asked to reduce {_display_name(name, data)} by {edit['requested_percent']:g}%.")
                else:
                    description = f"Trimmed to reach {edit['requested_percent']:g}% less {edit['label'].lower()}."
                descriptions.append(description)
            reason = " ".join(descriptions)
        else:
            reason = "Kept at its original amount."
        rows.append({
            "ingredient": name, "display_name": _display_name(name, data),
            "role": data["ingredients"].get(name, {}).get("role", "unknown"),
            "status": status, "original_g": _rounded(before, 1), "new_g": _rounded(after, 1),
            "delta_g": _rounded(after - before, 1),
            "delta_pct": _rounded(_percent_change(before, after), 1),
            "is_compensator": name in added, "reason": reason,
            "modification_ids": [edit["id"] for edit in edits],
        })
    return rows


def _format_modifications(results: list[dict]) -> list[dict]:
    """Round final modification outcomes without changing the pipeline's raw measurements."""
    output = deepcopy(results)
    for row in output:
        places = 1 if row["type"] == "ingredient" else 2
        for key in ("original_amount", "new_amount"):
            row[key] = _rounded(row[key], places)
        for key in ("requested_percent", "achieved_percent"):
            row[key] = _rounded(row[key], 1)
        for ingredient in row["affected_ingredients"]:
            ingredient["original_g"] = _rounded(ingredient["original_g"], 1)
            ingredient["new_g"] = _rounded(ingredient["new_g"], 1)
    return output


def _format_compensators(compensators: list[dict], data: dict) -> list[dict]:
    """Keep legacy compensator fields and add explanations and alternatives for review."""
    output = deepcopy(compensators)
    for row in output:
        row.setdefault("display_name", _display_name(row["ingredient"], data))
        row["grams"] = _rounded(row["grams"], 1)
        row["taste_boost"] = _rounded(row["taste_boost"])
        row["molecule_overlap"] = _rounded(row["molecule_overlap"])
        row["score"] = _rounded(row["score"], 3)
        row["axis_gains"] = {axis: _rounded(gain) for axis, gain in row["axis_gains"].items()}
        for alternative in row["alternatives"]:
            alternative.setdefault("display_name", _display_name(alternative["ingredient"], data))
            alternative["score"] = _rounded(alternative["score"], 3)
            alternative["grams_needed"] = _rounded(alternative["grams_needed"], 1)
    return output


def build_headline(comparisons: dict, scores: dict, compensator_count: int) -> dict:
    """Select at most four changes, prioritizing requested metrics, for a concise summary."""
    candidates = []
    for kind in ("nutrient", "chemical"):
        for row in comparisons[f"{kind}_comparison"]:
            if row["change_type"] != "unchanged":
                candidates.append({**row, "kind": kind})
    candidates.sort(key=lambda row: (not row["targeted"], -abs(row["delta_pct"] or 0)))
    keys = ("id", "kind", "label", "unit", "original_per_serving", "new_per_serving",
            "delta_per_serving", "delta_pct", "change_type")
    chosen = [{key: row[key] for key in keys} for row in candidates[:HEADLINE_METRIC_LIMIT]]
    phrases = []
    for row in chosen:
        delta = row["delta_per_serving"]
        direction = "less" if delta < 0 else "more"
        percent = f" ({row['delta_pct']:+g}%)" if row["delta_pct"] is not None else ""
        phrases.append(f"{abs(delta):g} {row['unit']} {direction} {row['label'].lower()}{percent}")
    summary = "Per serving: " + ", ".join(phrases) + "." if phrases else "No meaningful nutrient or chemical changes."
    summary += f" Taste retention {scores['taste_retention_pct']:g}%."
    summary += f" {compensator_count} compensator{'s' if compensator_count != 1 else ''} added."
    return {"summary_text": summary, "key_metrics": chosen}


def _contains_placeholder(value: object) -> bool:
    """Inspect scalar or field-level provenance so mixed real and estimated data stays honest."""
    if isinstance(value, dict):
        return any(_contains_placeholder(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_placeholder(item) for item in value)
    return isinstance(value, str) and "placeholder" in value.lower()


def data_quality(original_recipe: dict, final_recipe: dict, data: dict) -> dict:
    """Report provenance for ingredients actually used, retaining imported source notes."""
    meta = data.get("meta", {})
    names = list(dict.fromkeys([*original_recipe["ingredients"], *final_recipe["ingredients"]]))
    notes = []
    if meta.get("warning"):
        notes.append(meta["warning"])
    notes.extend(meta.get("notes", []))
    provenance = {}
    placeholder = False
    fields = ("data_quality", "data_source", "source", "sources", "source_metadata",
              "source_notes", "field_sources", "data_quality_notes")
    for name in names:
        info = data["ingredients"].get(name)
        if info is None:
            continue
        provenance[name] = {key: deepcopy(info[key]) for key in fields if key in info}
        quality = info.get("data_quality", info.get("data_source", meta.get("data_source", "unknown")))
        placeholder = placeholder or _contains_placeholder(quality)
        for field in ("source_notes", "data_quality_notes"):
            value = info.get(field, [])
            notes.extend(value if isinstance(value, list) else [value])
    unknown = deepcopy(original_recipe.get("unresolved_ingredients", []))
    if unknown:
        notes.append("Unknown ingredients contribute zero to nutrition, chemical and taste estimates.")
    # Source notes can be objects; equality-based deduplication preserves their original shape.
    unique_notes = []
    for note in notes:
        if note and note not in unique_notes:
            unique_notes.append(note)
    return {"data_source": meta.get("data_source", "unknown"),
            "placeholder_values": placeholder, "unknown_ingredients": unknown,
            "notes": unique_notes, "ingredient_provenance": provenance}


def build_response(original_recipe: dict, cut_state: dict, repair_state: dict,
                   options: dict, data: dict, goal: str | None = None,
                   reduce_percent: float | None = None) -> dict:
    """Turn all pipeline stages into the complete v2 response while retaining legacy keys."""
    options_used = {"max_compensators": 3, "exclude_compensators": [],
                    "servings": original_recipe["servings"], "include_trace": True,
                    **deepcopy(options)}
    servings = options_used["servings"]
    final_recipe = repair_state["recipe"]
    results = finalize_modification_results(original_recipe, final_recipe,
                                             cut_state["modifications"],
                                             cut_state["modification_results"], data)
    comparisons = comparison_rows(original_recipe, final_recipe, cut_state["modifications"],
                                  servings, data)
    scores = {key: (value if key == "target_reached" else _rounded(value, 1))
              for key, value in repair_state["scores"].items() if key != "by_axis"}
    scores["by_axis"] = {axis: _rounded(value, 1)
                         for axis, value in repair_state["scores"]["by_axis"].items()}
    compensators = _format_compensators(repair_state["added_compensators"], data)
    original_totals = totals(original_recipe["ingredients"], data)
    final_totals = totals(final_recipe["ingredients"], data)
    legacy_original, legacy_final = {}, {}
    for metric, group in (("sugar_g", "nutrients"), ("sodium_mg", "chemicals"), ("fat_g", "nutrients")):
        legacy_original[metric] = _rounded(original_totals[group].get(metric, 0.0))
        legacy_final[metric] = _rounded(final_totals[group].get(metric, 0.0))
    nutrition = {"original": legacy_original, "reformulated": legacy_final}
    for metric, saved, group in (("sugar_g", "sugar_saved_g", "nutrients"),
                                 ("sodium_mg", "sodium_saved_mg", "chemicals"),
                                 ("fat_g", "fat_saved_g", "nutrients")):
        nutrition[saved] = _rounded(original_totals[group].get(metric, 0.0) - final_totals[group].get(metric, 0.0))
    warning_details = build_warnings(original_recipe, final_recipe, results, repair_state,
                                     data, reduce_percent=reduce_percent)
    baseline = ", ".join(f"{axis} {value:.2f}" for axis, value in repair_state["original"].items())
    trace_detail = ([{"phase": "baseline", "text": f"Original taste: {baseline}."}]
                    + deepcopy(cut_state["trace_detail"]) + deepcopy(repair_state["trace_detail"]))
    if not options_used["include_trace"]:
        trace_detail = []
    axes = [{"axis": axis, "label": axis.capitalize(),
             "original": _rounded(repair_state["original"][axis]),
             "after_cut": _rounded(repair_state["after_cut"][axis]),
             "final": _rounded(repair_state["final"][axis]),
             "retention_pct": scores["by_axis"].get(axis),
             "affected": axis in repair_state["affected_axes"]} for axis in data["taste_axes"]]
    return {
        "schema_version": 2, "dish": original_recipe["dish"], "recipe_name": original_recipe["name"],
        "servings": servings, "goal": goal, "reduce_percent": reduce_percent,
        "original_recipe": {"ingredients": {name: _rounded(grams, 1) for name, grams in original_recipe["ingredients"].items()},
                            "tags": deepcopy(original_recipe["tags"])},
        "new_recipe": {"ingredients": {name: _rounded(grams, 1) for name, grams in final_recipe["ingredients"].items()},
                       "tags": deepcopy(final_recipe["tags"])},
        "added_compensators": compensators, "scores": scores,
        "new_flavor_notes": deepcopy(repair_state["new_flavor_notes"]),
        "lost_flavor_notes": deepcopy(repair_state["lost_flavor_notes"]), "nutrition": nutrition,
        "modification_results": _format_modifications(results),
        "ingredient_changes": ingredient_changes(original_recipe, final_recipe, results, compensators, data),
        **comparisons, "taste_profile": {"axes": axes, "affected_axes": list(repair_state["affected_axes"])},
        "headline": build_headline(comparisons, scores, len(compensators)),
        "warning_details": warning_details, "warnings": [row["message"] for row in warning_details],
        "badges": {"original": badges(original_totals, servings, data),
                   "reformulated": badges(final_totals, servings, data)},
        "trace_detail": trace_detail, "trace": [row["text"] for row in trace_detail],
        "data_source": data.get("meta", {}).get("data_source", "unknown"),
        "data_quality": data_quality(original_recipe, final_recipe, data), "options_used": options_used,
    }
