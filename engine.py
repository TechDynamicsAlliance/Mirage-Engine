"""MIRAGE engine — cut → measure deficit → compensate → score.

Per the GUIDE (Lesson 3):
1. Measure the original dish's perceived taste + flavor fingerprint.
2. Cut the chosen ingredient by X%.
3. Compute the deficit: how much perceived taste to win back (target: 95%).
4. Find compensators: must boost that taste, fit the dish type, not already in recipe.
   Rank by power × (1 + overlap).
5. Add greedily: best first, capped at max_g, at most 3 additions.
6. Score: taste retention %, flavor preserved %, new notes, savings, warnings, trace.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

# ── Goal definitions ────────────────────────────────────────────────
GOALS: dict[str, dict[str, str]] = {
    "sugar": {"target_ingredient": "sugar", "taste_field": "sweet_equiv_per_g", "nutrient": "sugar_g_per_g"},
    "salt":  {"target_ingredient": "salt",  "taste_field": "salty_equiv_per_g", "nutrient": "sodium_mg_per_g"},
    "fat":   {"target_ingredient": None,    "taste_field": None,                "nutrient": "fat_g_per_g"},
}

RETENTION_TARGET = 0.95  # aim for 95% of original perceived taste


# ── Errors ──────────────────────────────────────────────────────────
class MirageError(Exception):
    """Engine-level error (maps to HTTP 400)."""

class DishNotFound(MirageError):
    """Requested dish does not exist in the data (maps to HTTP 404)."""


# ── Data loading ────────────────────────────────────────────────────
def load_data(path: str | Path = None) -> dict:
    if path is None:
        path = Path(__file__).parent / "data" / "placeholder_data.json"
    with open(path) as f:
        return json.load(f)


# ── Reading schema v2 (the old flat keys still work as a fallback) ──
# Goal code still says "sweet_equiv_per_g". The data file now stores that
# number at taste_per_g.sweet. These helpers hide that move so the math
# above them does not change.
_TASTE_FIELD_TO_AXIS = {
    "sweet_equiv_per_g": "sweet",
    "salty_equiv_per_g": "salty",
}


def _taste_value(ing: dict | None, taste_field: str) -> float:
    """Read one taste-per-gram number.

    Schema v2 keeps the old sweet/salty figures under taste_per_g so a
    sugar or salt goal still sees the same boost it did before.
    """
    if not ing or not taste_field:
        return 0.0
    if "taste_per_g" in ing:
        axis = _TASTE_FIELD_TO_AXIS.get(taste_field, taste_field)
        return ing["taste_per_g"].get(axis, 0.0)
    return ing.get(taste_field, 0.0)


def _nutrient_value(ing: dict | None, key: str) -> float:
    """Read sugar or fat per gram.

    Missing keys mean 0, both in the nested block and in the old flat file.
    """
    old_keys = {"sugar_g": "sugar_g_per_g", "fat_g": "fat_g_per_g"}
    if not ing:
        return 0.0
    if "nutrients_per_g" in ing:
        return ing["nutrients_per_g"].get(key, 0.0)
    return ing.get(old_keys[key], 0.0)


def _sodium_value(ing: dict | None) -> float:
    """Read sodium in mg per gram. Missing means 0."""
    if not ing:
        return 0.0
    if "chemicals_per_g" in ing:
        return ing["chemicals_per_g"].get("sodium_mg", 0.0)
    return ing.get("sodium_mg_per_g", 0.0)


def _compensator_block(ing: dict) -> dict | None:
    """Return compensator rules, or None when the ingredient is not one.

    Schema v2 uses a nested block. The old file used compensator_for / fits / max_g.
    Fat was renamed to the richness axis; both names are accepted.
    """
    if "compensator" in ing:
        block = ing["compensator"]
        return {
            "compensates": list(block.get("compensates", [])),
            "fits": list(block.get("fits", [])),
            "max_g": block.get("max_g", 5),
            "caution": block.get("caution"),
        }
    if "compensator_for" in ing:
        return {
            "compensates": list(ing.get("compensator_for", [])),
            "fits": list(ing.get("fits", [])),
            "max_g": ing.get("max_g", 5),
            "caution": ing.get("caution"),
        }
    return None


# ── Helper functions ────────────────────────────────────────────────
def fingerprint(ingredients: dict[str, float], data: dict) -> set[str]:
    """Set of all flavor molecules across a recipe's ingredients."""
    mols: set[str] = set()
    for name in ingredients:
        ing = data["ingredients"].get(name)
        if ing:
            mols.update(ing.get("molecules", []))
    return mols


def perceived_taste(ingredients: dict[str, float], taste_field: str, data: dict) -> float:
    """Sum of (grams × taste-equivalent-per-gram) across all ingredients.

    This is the "how sweet / salty does it taste" number the deficit uses.
    """
    total = 0.0
    for name, grams in ingredients.items():
        ing = data["ingredients"].get(name)
        if ing:
            total += grams * _taste_value(ing, taste_field)
    return total


def totals(ingredients: dict[str, float], data: dict) -> dict[str, float]:
    """Compute actual sugar (g), sodium (mg), and fat (g) totals.

    Only these three are returned today because the legacy response shows
    them. Rounding to 2 decimals happens here, at the edge of that response.
    """
    sugar_g = 0.0
    sodium_mg = 0.0
    fat_g = 0.0
    for name, grams in ingredients.items():
        ing = data["ingredients"].get(name)
        if ing:
            sugar_g += grams * _nutrient_value(ing, "sugar_g")
            sodium_mg += grams * _sodium_value(ing)
            fat_g += grams * _nutrient_value(ing, "fat_g")
    return {"sugar_g": round(sugar_g, 2), "sodium_mg": round(sodium_mg, 2), "fat_g": round(fat_g, 2)}


def rank_compensators(
    taste_field: str,
    dish_tags: list[str],
    dish_molecules: set[str],
    current_ingredients: set[str],
    data: dict,
) -> list[tuple[str, float, dict]]:
    """Return compensator candidates sorted by score (descending).

    Score = power × (1 + overlap), where overlap is the share of the
    candidate's molecules that the dish already has.
    """
    candidates = []
    for name, info in data["ingredients"].items():
        comp = _compensator_block(info)
        if comp is None:
            continue
        # Must compensate for the right taste.
        # Schema v2 calls the old "fat" axis "richness".
        goal_taste = "sweet" if taste_field == "sweet_equiv_per_g" else "salty" if taste_field == "salty_equiv_per_g" else "fat"
        accepted = {goal_taste}
        if goal_taste == "fat":
            accepted.add("richness")
        if not any(item in accepted for item in comp["compensates"]):
            continue
        # Must fit the dish's tags
        if not any(t in comp["fits"] for t in dish_tags):
            continue
        # Must not already be in the recipe
        if name in current_ingredients:
            continue

        power = _taste_value(info, taste_field) if taste_field else 0.5  # fat compensators get a baseline
        cand_molecules = set(info.get("molecules", []))
        if cand_molecules:
            overlap = len(cand_molecules & dish_molecules) / len(cand_molecules)
        else:
            overlap = 0.0
        score = power * (1 + overlap)
        candidates.append((name, score, info))

    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates


# ── Main engine ─────────────────────────────────────────────────────
def reformulate(
    dish: str,
    goal: str,
    reduce_percent: int,
    data: dict | None = None,
) -> dict[str, Any]:
    """Run the MIRAGE reformulation algorithm.

    Returns a dictionary with all the fields the frontend needs (per GUIDE Lesson 6).
    """
    if data is None:
        data = load_data()

    # ── Validate inputs ─────────────────────────────────────────────
    if goal not in GOALS:
        raise MirageError(f"Unknown goal '{goal}'. Choose from: {list(GOALS.keys())}")
    if not (1 <= reduce_percent <= 80):
        raise MirageError(f"reduce_percent must be 1–80, got {reduce_percent}")

    dishes = data.get("dishes", {})
    if dish not in dishes:
        raise DishNotFound(f"Dish '{dish}' not found. Available: {list(dishes.keys())}")

    goal_info = GOALS[goal]
    dish_def = dishes[dish]

    # Deep copy so we never mutate the original data
    original_ingredients = copy.deepcopy(dish_def["ingredients"])
    new_ingredients = copy.deepcopy(dish_def["ingredients"])
    tags = dish_def.get("tags", [])
    trace: list[str] = []
    warnings: list[str] = []

    # ── STEP 1 & 2: Measure original ────────────────────────────────
    orig_totals = totals(original_ingredients, data)
    orig_fingerprint = fingerprint(original_ingredients, data)

    taste_field = goal_info["taste_field"]
    nutrient_field = goal_info["nutrient"]

    if taste_field:
        orig_perceived = perceived_taste(original_ingredients, taste_field, data)
        trace.append(f"Original perceived {goal} taste: {orig_perceived:.1f}")
    else:
        orig_perceived = None

    # ── STEP 3: Cut ─────────────────────────────────────────────────
    # For sugar/salt: cut the specific target ingredient.
    # For fat: cut all high-fat ingredients proportionally.
    target_ing = goal_info["target_ingredient"]

    if target_ing and target_ing in new_ingredients:
        old_amount = new_ingredients[target_ing]
        cut_amount = old_amount * (reduce_percent / 100)
        new_ingredients[target_ing] = round(old_amount - cut_amount, 1)
        # Round up to next 0.1 g to avoid missing the target (GUIDE Lesson 2, fix #9)
        new_ingredients[target_ing] = math.floor(new_ingredients[target_ing] * 10) / 10
        trace.append(f"Cut {target_ing}: {old_amount}g → {new_ingredients[target_ing]}g ({reduce_percent}% reduction)")
    elif goal == "fat":
        # Cut all fat contributors proportionally
        fat_sources = []
        for name, grams in new_ingredients.items():
            ing = data["ingredients"].get(name, {})
            fat_per_g = _nutrient_value(ing, "fat_g")
            if fat_per_g > 0.1:  # only meaningful fat sources
                fat_sources.append((name, grams, fat_per_g))
        for name, grams, _ in fat_sources:
            cut = grams * (reduce_percent / 100)
            new_ingredients[name] = round(grams - cut, 1)
            trace.append(f"Cut {name}: {grams}g → {new_ingredients[name]}g ({reduce_percent}%)")
    else:
        trace.append(f"Target ingredient '{target_ing}' not in this dish. No direct cut applied.")

    # ── STEP 4: Compute deficit ─────────────────────────────────────
    added_compensators: list[dict] = []

    if taste_field and orig_perceived and orig_perceived > 0:
        new_perceived = perceived_taste(new_ingredients, taste_field, data)
        target = RETENTION_TARGET * orig_perceived
        deficit = target - new_perceived
        trace.append(f"After cut: perceived taste = {new_perceived:.1f}, target = {target:.1f}, deficit = {max(0, deficit):.1f}")

        # ── STEP 5: Find & add compensators ─────────────────────────
        if deficit > 0:
            candidates = rank_compensators(
                taste_field, tags, orig_fingerprint,
                set(new_ingredients.keys()), data,
            )

            for name, score, info in candidates:
                if deficit <= 0 or len(added_compensators) >= 3:
                    break
                comp = _compensator_block(info) or {}
                max_g = comp.get("max_g", 5)
                power = _taste_value(info, taste_field)
                if power <= 0:
                    continue
                # How many grams do we need?
                needed_g = deficit / power
                actual_g = min(needed_g, max_g)
                actual_g = math.ceil(actual_g * 10) / 10  # round up

                boost = actual_g * power
                new_ingredients[name] = actual_g
                deficit -= boost

                cand_molecules = set(info.get("molecules", []))
                overlap = len(cand_molecules & orig_fingerprint) / len(cand_molecules) if cand_molecules else 0

                comp_entry = {
                    "ingredient": name,
                    "grams": actual_g,
                    "taste_boost": round(boost, 2),
                    "molecule_overlap": round(overlap, 2),
                    "score": round(score, 3),
                }
                caution = comp.get("caution")
                if caution:
                    comp_entry["caution"] = caution
                    warnings.append(f"{name}: {caution}")

                added_compensators.append(comp_entry)
                trace.append(f"Added {name}: {actual_g}g (+{boost:.1f} taste, {overlap:.0%} molecule overlap)")

            final_perceived = perceived_taste(new_ingredients, taste_field, data)
            trace.append(f"Final perceived taste: {final_perceived:.1f} / {orig_perceived:.1f} = {final_perceived / orig_perceived:.0%}")

    # ── STEP 6: Score ───────────────────────────────────────────────
    new_totals = totals(new_ingredients, data)
    new_fingerprint = fingerprint(new_ingredients, data)

    shared = orig_fingerprint & new_fingerprint
    all_mols = orig_fingerprint | new_fingerprint
    flavor_preserved_pct = round(len(shared) / len(orig_fingerprint) * 100, 1) if orig_fingerprint else 100.0
    new_flavor_notes = sorted(new_fingerprint - orig_fingerprint)

    if taste_field and orig_perceived and orig_perceived > 0:
        final_perceived = perceived_taste(new_ingredients, taste_field, data)
        taste_retention_pct = round(min(final_perceived / orig_perceived * 100, 100.0), 1)
        target_reached = taste_retention_pct >= RETENTION_TARGET * 100
    else:
        taste_retention_pct = None
        target_reached = None

    if goal == "sugar":
        saved_label = "sugar_saved_g"
        saved_value = round(orig_totals["sugar_g"] - new_totals["sugar_g"], 2)
    elif goal == "salt":
        saved_label = "sodium_saved_mg"
        saved_value = round(orig_totals["sodium_mg"] - new_totals["sodium_mg"], 2)
    else:
        saved_label = "fat_saved_g"
        saved_value = round(orig_totals["fat_g"] - new_totals["fat_g"], 2)

    if target_reached is False:
        warnings.append(
            f"Could not reach {RETENTION_TARGET * 100:.0f}% taste retention at {reduce_percent}% reduction. "
            f"Achieved {taste_retention_pct}%. Try a lower reduction percentage."
        )

    return {
        "dish": dish,
        "goal": goal,
        "reduce_percent": reduce_percent,
        "original_recipe": {
            "ingredients": {k: v for k, v in original_ingredients.items()},
            "tags": tags,
        },
        "new_recipe": {
            "ingredients": {k: v for k, v in new_ingredients.items()},
            "tags": tags,
        },
        "added_compensators": added_compensators,
        "scores": {
            "taste_retention_pct": taste_retention_pct,
            "flavor_preserved_pct": flavor_preserved_pct,
            "target_reached": target_reached,
        },
        "new_flavor_notes": new_flavor_notes,
        "nutrition": {
            "original": orig_totals,
            "reformulated": new_totals,
            saved_label: saved_value,
        },
        "warnings": warnings,
        "trace": trace,
        "data_source": data.get("meta", {}).get("data_source", "unknown"),
    }


def list_dishes(data: dict | None = None) -> list[dict]:
    """List available dishes for the frontend dropdown."""
    if data is None:
        data = load_data()
    result = []
    for name, dish in data.get("dishes", {}).items():
        available_goals = []
        for goal_name, goal_info in GOALS.items():
            target = goal_info["target_ingredient"]
            if target is None or target in dish["ingredients"]:
                available_goals.append(goal_name)
        result.append({
            "dish": name,
            "goals": available_goals,
            "ingredients": list(dish["ingredients"].keys()),
        })
    return result
