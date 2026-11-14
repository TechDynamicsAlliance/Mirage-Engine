"""Frontend detail and slider metadata, using the same locks as the cutting algorithm."""

import math
from metrics import eligible_contributions, IMPLICIT_MAX_CUT
from warning_rules import badges


def build_detail(baseline: dict, data: dict) -> dict:
    """Decorate an unrounded baseline with portions and feasible reductions for the UI."""
    recipe = baseline["recipe"]
    servings = recipe["servings"]
    ingredients = []
    modifiable = {"ingredients": [], "nutrients": [], "chemicals": []}
    dv = {"nutrients": {}, "chemicals": {}}
    for name, grams in recipe["ingredients"].items():
        info = data["ingredients"].get(name, {})
        common = {"name": name, "display_name": info.get("display_name", name), "grams": round(grams, 1),
                  "role": info.get("role", "unknown"), "is_core": name in recipe["core_ingredients"]}
        amounts = {group: {metric: round(by_name[name], 2) for metric, by_name in baseline["contributions"][group].items()}
                   for group in ("nutrients", "chemicals")}
        ingredients.append({**common, **amounts})
        modifiable["ingredients"].append({**common, "can_reduce": True, "can_remove": True, "max_percent": 99,
                                          "note": "Changing a core ingredient can change the identity of this dish." if common["is_core"] else None})
    for kind, group, definitions in (("nutrient", "nutrients", "nutrient_defs"), ("chemical", "chemicals", "chemical_defs")):
        for definition in data[definitions]:
            metric = definition["id"]
            total = baseline["totals"][group][metric]
            reference = definition.get("daily_value")
            dv[group][metric] = round(total / servings / reference * 100, 1) if reference else None
            if total <= 0:
                continue
            eligible = eligible_contributions(recipe, kind, metric, total, [], data)
            contributors = baseline["contributions"][group][metric]
            modifiable[group].append({"id": metric, "label": definition["label"], "unit": definition["unit"],
                                      "total": round(total, 2), "per_serving": round(total / servings, 2), "max_percent": 80,
                                      "max_feasible_percent": math.floor(IMPLICIT_MAX_CUT * sum(eligible.values()) / total * 100),
                                      "top_contributors": [{"ingredient": name, "share_pct": round(amount / total * 100, 1)}
                                                           for name, amount in sorted(contributors.items(), key=lambda item: item[1], reverse=True) if amount > 0]})
    return {**baseline, "dish": recipe["dish"], "display_name": recipe["name"], "servings": servings,
            "tags": list(recipe["tags"]), "ingredients": ingredients,
            "totals": {group: {key: round(value, 2) for key, value in values.items()} for group, values in baseline["totals"].items()},
            "per_serving": {group: {key: round(value, 2) for key, value in values.items()} for group, values in baseline["per_serving"].items()},
            "dv_pct": dv, "daily_reference_label": "approx. % of daily reference",
            "badges": badges(baseline["totals"], servings, data), "modifiable": modifiable}
