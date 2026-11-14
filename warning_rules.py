"""Explain practical limits of recipe changes without claiming laboratory precision."""

from metrics import totals

TASTE_TARGET_PCT = 95
TEXTURE_CUT_PCT = 50
CORE_CUT_PCT = 30
SIDE_EFFECT_PCT = 5
HIGH_DAILY_REFERENCE_PCT = 20
SWEETENER_TAGS = ("dessert", "baking")
SALT_FUNCTION_TAGS = ("baking", "bread", "cured", "fermented")
BADGE_METRICS = {
    "sodium_mg": "high-sodium", "sugar_g": "high-sugar", "fat_g": "high-fat",
    "saturated_fat_g": "high-saturated-fat", "cholesterol_mg": "high-cholesterol",
}


def badges(amounts: dict, servings: float, data: dict) -> list[str]:
    """Flag high per-serving reference percentages so portions are compared consistently."""
    result = []
    for group, definitions in (("nutrients", "nutrient_defs"), ("chemicals", "chemical_defs")):
        for definition in data[definitions]:
            metric = definition["id"]
            daily = definition.get("daily_value")
            if metric in BADGE_METRICS and daily and amounts[group].get(metric, 0) / servings / daily * 100 >= HIGH_DAILY_REFERENCE_PCT:
                result.append(BADGE_METRICS[metric])
    return result


def build_warnings(original_recipe: dict, final_recipe: dict, modification_results: list[dict],
                   repair_state: dict, data: dict, reduce_percent: float | None = None) -> list[dict]:
    """Apply deterministic warning rules to the final recipe, including compensation side effects."""
    warnings = []

    def add(code: str, severity: str, message: str, related: list):
        """Append one structured warning so the legacy message list can use the same order."""
        warnings.append({"code": code, "severity": severity, "message": message, "related": related})

    score = repair_state["scores"]
    if not score["target_reached"]:
        requested = reduce_percent if reduce_percent is not None else max(
            (row["requested_percent"] if row["requested_percent"] is not None else 100
             for row in modification_results), default=0)
        add("TARGET_MISSED", "warning",
            f"Could not reach 95% taste retention at {requested:g}% reduction. "
            f"Achieved {score['taste_retention_pct']:.1f}%. Try a lower reduction percentage.",
            list(repair_state["affected_axes"]))
        if repair_state.get("limit_reached"):
            add("COMPENSATION_LIMIT", "caution", "Taste repair stopped at a compensator count, amount or conflict limit.",
                list(repair_state["affected_axes"]))
    added = repair_state["added_compensators"]
    richness_repaired = any(data["ingredients"][row["ingredient"]].get("compensator", {}).get("compensates", []).count("richness")
                           for row in added)
    for row in added:
        caution = row.get("caution")
        if caution:
            add("COMPENSATOR_CAUTION", "caution", f"{row.get('display_name', row['ingredient'])}: {caution}", [row["ingredient"]])

    tags = original_recipe["tags"]
    for name, before in original_recipe["ingredients"].items():
        after = final_recipe["ingredients"].get(name, 0)
        cut_pct = (before - after) / before * 100 if before else 0
        info = data["ingredients"].get(name, {})
        label = info.get("display_name", name)
        role = info.get("role")
        if role == "sweetener" and cut_pct > TEXTURE_CUT_PCT and any(tag in tags for tag in SWEETENER_TAGS):
            add("TEXTURE_RISK_SWEETENER", "caution", f"Cutting {label} by more than 50% may change browning, moisture and texture.", [name])
        if role == "fat_source" and cut_pct > TEXTURE_CUT_PCT and not richness_repaired:
            add("MOUTHFEEL_RISK_FAT", "caution", f"Cutting {label} by more than 50% may reduce creaminess and mouthfeel.", [name])
        if name == "salt" and cut_pct > TEXTURE_CUT_PCT and any(tag in tags for tag in SALT_FUNCTION_TAGS):
            add("SALT_FUNCTION_RISK", "caution", "Salt affects texture and food safety in baking, bread, cured and fermented foods.", [name])
        if name in original_recipe["core_ingredients"] and (cut_pct > CORE_CUT_PCT or name not in final_recipe["ingredients"]):
            add("CORE_INGREDIENT_CHANGED", "warning", f"Changing core ingredient {label} this much means this is no longer really the same dish.", [name])

    before_totals = totals(original_recipe["ingredients"], data)
    after_totals = totals(final_recipe["ingredients"], data)
    targeted = {(row["type"], row["target"]) for row in modification_results}
    for group, definitions, kind in (("nutrients", "nutrient_defs", "nutrient"), ("chemicals", "chemical_defs", "chemical")):
        for definition in data[definitions]:
            metric = definition["id"]
            before, after = before_totals[group][metric], after_totals[group][metric]
            if definition.get("group") == "preservatives" and after < before:
                add("PRESERVATIVE_REDUCED", "warning", f"{definition['label']} was reduced: shelf life is shorter, keep refrigerated and eat sooner.", [metric])
            if (kind, metric) in targeted:
                continue
            worsening = after - before if definition["direction"] == "lower_is_better" else before - after
            if worsening > 0 and (before == 0 or worsening / before * 100 > SIDE_EFFECT_PCT):
                word = "increased" if after > before else "decreased"
                add("SIDE_EFFECT_WORSENED", "info", f"{definition['label']} {word} by {abs(after - before):.2f} {definition['unit']} across the dish.", [metric])
    for row in modification_results:
        if row["status"] in ("partial", "not_possible"):
            add("PARTIAL_MODIFICATION", "caution", f"{row['label']}: {row['note']}", [row["id"], row["target"]])
    for unknown in original_recipe.get("unresolved_ingredients", []):
        add("UNKNOWN_INGREDIENT", "caution", f"Unknown ingredient '{unknown['name']}': its nutrition is not included in these numbers.", [unknown["name"]])
    return warnings
