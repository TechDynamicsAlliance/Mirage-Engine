"""Deterministic taste repair with explicit ingredient, metric and mass limits."""

from __future__ import annotations

from copy import deepcopy
import math

from catalog import resolve_name
from metrics import fingerprint, taste_vector, totals

RETENTION_TARGET = 0.95
MIN_USEFUL_GAIN = 0.01
MAX_GIVEBACK_SHARE = 0.25
MAX_COMPENSATOR_MASS_SHARE = 0.10
EPSILON = 1e-10


def _weights(original: dict, current: dict, affected: list[str]) -> tuple[dict, dict]:
    """Weight remaining relative deficits so gains on another axis update the next choice."""
    deficits = {axis: max(0.0, RETENTION_TARGET * original[axis] - current[axis])
                for axis in affected}
    relative = {axis: deficit / original[axis] for axis, deficit in deficits.items()
                if deficit > EPSILON}
    total = sum(relative.values())
    return deficits, {axis: value / total for axis, value in relative.items()} if total else {}


def _rank(weights: dict, recipe: dict, original_molecules: set, forbidden: set,
          data: dict) -> list[dict]:
    """Rank usable candidates by weighted taste power and overlap, retaining catalog tie order."""
    candidates = []
    tags = set(recipe["tags"])
    for name, info in data["ingredients"].items():
        block = info.get("compensator")
        if (not block or name in forbidden or not tags.intersection(block.get("fits", []))
                or not set(weights).intersection(block.get("compensates", []))):
            continue
        powers = info.get("taste_per_g", {})
        contributions = {axis: weight * powers.get(axis, 0.0) for axis, weight in weights.items()}
        if not contributions or max(contributions.values()) <= 0:
            continue
        molecules = set(info.get("molecules", []))
        overlap = len(molecules & original_molecules) / len(molecules) if molecules else 0.0
        candidates.append({"ingredient": name, "info": info, "block": block,
                           "axis": max(contributions, key=contributions.get),
                           "molecule_overlap": overlap,
                           "score": sum(contributions.values()) * (1 + overlap)})
    return sorted(candidates, key=lambda row: row["score"], reverse=True)


def _budgets(original_recipe: dict, cut_recipe: dict, modifications: list[dict], data: dict) -> dict:
    """Reserve one giveback budget per targeted metric so several additions cannot each spend it."""
    original = totals(original_recipe["ingredients"], data)
    cut = totals(cut_recipe["ingredients"], data)
    budgets = {}
    for edit in modifications:
        if edit["type"] not in ("nutrient", "chemical"):
            continue
        group = "nutrients" if edit["type"] == "nutrient" else "chemicals"
        key = (group, edit["target"])
        budgets[key] = MAX_GIVEBACK_SHARE * max(0.0, original[group][key[1]] - cut[group][key[1]])
    return budgets


def _proposal(candidate: dict, deficits: dict, original: dict, remaining_mass: float,
              budgets: dict, spent: dict) -> dict:
    """Round useful grams upward inside floored hard caps, preserving every limit after rounding."""
    powers = candidate["info"].get("taste_per_g", {})
    axis = candidate["axis"]
    needed = deficits[axis] / powers[axis]
    cap = min(max(0.0, candidate["block"].get("max_g", 0.0)), max(0.0, remaining_mass))
    reasons = []
    if candidate["block"].get("max_g", 0.0) < needed:
        reasons.append("safe cap")
    if remaining_mass < needed:
        reasons.append("10% total mass limit")
    for key, budget in budgets.items():
        content = "nutrients_per_g" if key[0] == "nutrients" else "chemicals_per_g"
        per_g = candidate["info"].get(content, {}).get(key[1], 0.0)
        if per_g > 0:
            allowed = max(0.0, budget - spent.get(key, 0.0)) / per_g
            if allowed < needed:
                reasons.append(f"25% giveback limit for {key[1]}")
            cap = min(cap, allowed)
    grams = min(math.ceil(needed * 10 - EPSILON) / 10, math.floor(cap * 10) / 10)
    gains = {axis: grams * power for axis, power in powers.items()}
    useful = grams > 0 and any(
        gains.get(axis, 0.0) / original[axis] >= MIN_USEFUL_GAIN - EPSILON
        for axis, deficit in deficits.items() if deficit > EPSILON)
    return {"grams": grams, "grams_needed": needed, "gains": gains,
            "useful": useful, "limits": reasons}


def _alternatives(candidates: list[dict], chosen: str, deficits: dict, original: dict,
                  remaining_mass: float, budgets: dict, spent: dict) -> list[dict]:
    """Show up to three other feasible, useful choices so alternatives respect the same limits."""
    alternatives = []
    for candidate in candidates:
        if candidate["ingredient"] == chosen:
            continue
        proposal = _proposal(candidate, deficits, original, remaining_mass, budgets, spent)
        if not proposal["useful"]:
            continue
        alternatives.append({"ingredient": candidate["ingredient"],
                             "display_name": candidate["info"].get("display_name", candidate["ingredient"]),
                             "score": candidate["score"], "grams_needed": proposal["grams_needed"],
                             "reason_not_chosen": "Ranked behind the selected candidate for the remaining taste deficits."})
        if len(alternatives) == 3:
            break
    return alternatives


def repair(original_recipe: dict, cut_state: dict, options: dict, data: dict) -> dict:
    """Restore affected tastes greedily without undoing user edits or exceeding shared budgets.

    All scores and vectors stay unrounded for the response builder. Nutrition and
    taste are estimates from the supplied catalog; this function does not fetch
    data or modify its inputs. Exclusions, touched foods and original ingredients
    cannot reappear as compensators.
    """
    recipe = deepcopy(cut_state["recipe"])
    original = taste_vector(original_recipe["ingredients"], data)
    after_cut = taste_vector(recipe["ingredients"], data)
    current = dict(after_cut)
    affected = [axis for axis in data["taste_axes"]
                if original[axis] > 0 and after_cut[axis] < RETENTION_TARGET * original[axis]]
    original_molecules = set(fingerprint(original_recipe["ingredients"], data))
    forbidden = set(original_recipe["ingredients"]) | set(recipe["ingredients"])
    forbidden.update(cut_state.get("touched_ingredients", []))
    forbidden.update(resolve_name(name, data) or name for name in options.get("exclude_compensators", []))
    max_compensators = options.get("max_compensators", 3)
    max_mass = sum(original_recipe["ingredients"].values()) * MAX_COMPENSATOR_MASS_SHARE
    budgets = _budgets(original_recipe, recipe, cut_state.get("modifications", []), data)
    spent = {key: 0.0 for key in budgets}
    added = []
    trace = []
    capped = False
    mass = 0.0
    deficits, weights = _weights(original, current, affected)
    for axis in data["taste_axes"]:
        trace.append({"phase": "deficit", "text": (
            f"{axis}: original {original[axis]:.3f}, after cut {after_cut[axis]:.3f}, "
            f"95% target {RETENTION_TARGET * original[axis]:.3f}, deficit {deficits.get(axis, 0.0):.3f}.")})

    while weights and len(added) < max_compensators:
        candidates = _rank(weights, recipe, original_molecules, forbidden, data)
        if not candidates:
            break
        selected = None
        for candidate in candidates:
            proposal = _proposal(candidate, deficits, original, max_mass - mass, budgets, spent)
            capped = capped or bool(proposal["limits"])
            if not proposal["useful"]:
                detail = "; ".join(proposal["limits"])
                trace.append({"phase": "compensate", "text": (
                    f"Skipped {candidate['ingredient']}: {proposal['grams']:g} g would recover less than "
                    f"1 percentage point on any remaining affected axis"
                    f"{'; ' + detail if detail else ''}.")})
                forbidden.add(candidate["ingredient"])
                continue
            selected = (candidate, proposal)
            break
        if selected is None:
            break
        candidate, proposal = selected
        name, grams, axis = candidate["ingredient"], proposal["grams"], candidate["axis"]
        alternatives = _alternatives(candidates, name, deficits, original, max_mass - mass, budgets, spent)
        info, block = candidate["info"], candidate["block"]
        mechanism = block.get("mechanism", "taste_compensation")
        mechanism_text = data.get("mechanisms", {}).get(mechanism, {}).get("plain_text", "Restores perceived taste.")
        entry = {"ingredient": name, "display_name": info.get("display_name", name),
                 "grams": grams, "taste_boost": proposal["gains"].get(axis, 0.0),
                 "molecule_overlap": candidate["molecule_overlap"], "score": candidate["score"],
                 "axis": axis, "axis_gains": proposal["gains"], "mechanism": mechanism,
                 "reason": (f"{mechanism_text} Added {grams:g} g for "
                            f"{proposal['gains'].get(axis, 0.0):.2f} {axis} taste units."),
                 "alternatives": alternatives}
        if block.get("caution"):
            entry["caution"] = block["caution"]
        added.append(entry)
        recipe["ingredients"][name] = grams
        forbidden.add(name)
        mass += grams
        for key in budgets:
            content = "nutrients_per_g" if key[0] == "nutrients" else "chemicals_per_g"
            spent[key] += grams * info.get(content, {}).get(key[1], 0.0)
        current = taste_vector(recipe["ingredients"], data)
        deficits, weights = _weights(original, current, affected)
        gain_text = ", ".join(f"{key} +{gain:.3f}" for key, gain in proposal["gains"].items() if gain > 0)
        limits = "; " + "; ".join(proposal["limits"]) if proposal["limits"] else ""
        trace.append({"phase": "compensate", "text": (
            f"Added {name}: {grams:g} g ({gain_text}), score {candidate['score']:.3f}, "
            f"molecule overlap {candidate['molecule_overlap']:.1%}{limits}.")})

    by_axis = {axis: min(100.0, current[axis] / original[axis] * 100) if original[axis] > 0 else 100.0
               for axis in data["taste_axes"]}
    final_molecules = set(fingerprint(recipe["ingredients"], data))
    scores = {"taste_retention_pct": min((by_axis[axis] for axis in affected), default=100.0),
              "flavor_preserved_pct": (len(final_molecules & original_molecules) / len(original_molecules) * 100
                                       if original_molecules else 100.0),
              "target_reached": all(by_axis[axis] >= RETENTION_TARGET * 100 - EPSILON for axis in affected),
              "by_axis": by_axis}
    for axis in data["taste_axes"]:
        trace.append({"phase": "score", "text": (
            f"{axis}: final {current[axis]:.3f} / original {original[axis]:.3f}; "
            f"retention {by_axis[axis]:.2f}%{' (affected)' if axis in affected else ''}.")})
    return {"recipe": recipe, "original": original, "after_cut": after_cut, "final": current,
            "affected_axes": affected, "added_compensators": added, "scores": scores,
            "new_flavor_notes": sorted(final_molecules - original_molecules),
            "lost_flavor_notes": sorted(original_molecules - final_molecules),
            "trace_detail": trace,
            "limit_reached": bool(weights) and (capped or len(added) >= max_compensators)}
