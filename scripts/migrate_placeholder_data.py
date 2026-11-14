"""One-off migration of data/placeholder_data.json to schema version 2.

What it does: reads the old flat ingredient file, copies the taste, sugar,
sodium, fat, molecule, and compensator-cap numbers unchanged, then fills in
the nutrients, chemicals, dishes, and catalog rows the v2 engine needs.

Why: the engine is being rebuilt against a stable local file before any real
nutrition source is fetched. Re-running this after the file is already
version 2 does nothing, so you cannot accidentally overwrite the catalog.

No network. Every number written here is an approximation.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "placeholder_data.json"

ROLES = {
    "structural",
    "seasoning",
    "fat_source",
    "sweetener",
    "liquid",
    "aromatic",
    "condiment",
    "thickener",
}

# Old compensator axis "fat" is the richness axis in v2.
AXIS_RENAME = {"fat": "richness"}


def _macros(protein: float, carbs: float, fat: float, sugar: float, sat: float, fiber: float, cholesterol: float) -> dict:
    """Build the per-gram nutrient block and the matching calorie estimate.

    Calories use 4 kcal/g protein, 4 kcal/g carbs, and 9 kcal/g fat.
    That is the check the tests apply. It is not a lab measurement.
    """
    if sugar > carbs + 1e-9:
        raise ValueError(f"sugar {sugar} is above carbs {carbs}")
    if sat > fat + 1e-9:
        raise ValueError(f"saturated fat {sat} is above fat {fat}")
    calories = round(4 * protein + 4 * carbs + 9 * fat, 6)
    return {
        "calories_kcal": calories,
        "fat_g": fat,
        "saturated_fat_g": sat,
        "carbs_g": carbs,
        "sugar_g": sugar,
        "fiber_g": fiber,
        "protein_g": protein,
        "cholesterol_mg": cholesterol,
    }


def _ingredient(
    display_name: str,
    aliases: list[str],
    category: str,
    role: str,
    nutrients: dict,
    chemicals: dict,
    taste: dict,
    molecules: list[str],
    compensator: dict | None = None,
) -> dict:
    """Assemble one catalog row. Role is checked so a typo cannot sneak in."""
    if role not in ROLES:
        raise ValueError(f"bad role {role} on {display_name}")
    row = {
        "display_name": display_name,
        "aliases": list(aliases),
        "category": category,
        "role": role,
        "nutrients_per_g": nutrients,
        "chemicals_per_g": {key: value for key, value in chemicals.items() if value},
        "taste_per_g": taste,
        "molecules": list(molecules),
        "data_quality": "placeholder_approx",
    }
    if compensator is not None:
        row["compensator"] = compensator
    return row


def _defs() -> dict:
    """Top-level lists that are not ingredients: axes, nutrients, chemicals, mechanisms.

    Daily values are rough FDA-style reference amounts. The [VERIFY] note tells
    the frontend to say "approx. % of daily reference", not a precise %DV.
    """
    note = (
        "Every number in this file is an approximation from general nutrition knowledge "
        "(data_quality: placeholder_approx). It is not a lab measurement and not a citation. "
        "Daily values are rough FDA-style references [VERIFY]. Show them as "
        "approx. % of daily reference, not as a precise percent daily value. "
        "Calories are 4*protein + 4*carbs + 9*fat from the macros in this file."
    )
    return {
        "meta": {
            "schema_version": 2,
            "data_source": "placeholder",
            "warning": note,
            "notes": [
                "[VERIFY] Nutrient daily values, and the 400 mg caffeine reference, are rough guides for the demo, not personal nutrition advice."
            ],
        },
        "taste_axes": ["sweet", "salty", "umami", "richness"],
        "nutrient_defs": [
            {"id": "calories_kcal", "label": "Calories", "unit": "kcal", "direction": "lower_is_better", "daily_value": 2000},
            {"id": "fat_g", "label": "Fat", "unit": "g", "direction": "lower_is_better", "daily_value": 78},
            {"id": "saturated_fat_g", "label": "Saturated fat", "unit": "g", "direction": "lower_is_better", "daily_value": 20},
            {"id": "carbs_g", "label": "Carbohydrates", "unit": "g", "direction": "lower_is_better", "daily_value": 275},
            {"id": "sugar_g", "label": "Sugar", "unit": "g", "direction": "lower_is_better", "daily_value": 50},
            {"id": "fiber_g", "label": "Fiber", "unit": "g", "direction": "higher_is_better", "daily_value": 28},
            {"id": "protein_g", "label": "Protein", "unit": "g", "direction": "higher_is_better", "daily_value": 50},
            {"id": "cholesterol_mg", "label": "Cholesterol", "unit": "mg", "direction": "lower_is_better", "daily_value": 300},
        ],
        "chemical_defs": [
            {"id": "sodium_mg", "label": "Sodium", "unit": "mg", "direction": "lower_is_better", "daily_value": 2300, "group": None},
            {"id": "msg_g", "label": "MSG", "unit": "g", "direction": "lower_is_better", "daily_value": None, "group": None},
            {"id": "sodium_benzoate_mg", "label": "Sodium benzoate", "unit": "mg", "direction": "lower_is_better", "daily_value": None, "group": "preservatives"},
            {"id": "sodium_nitrite_mg", "label": "Sodium nitrite", "unit": "mg", "direction": "lower_is_better", "daily_value": None, "group": "preservatives"},
            {"id": "tartrazine_mg", "label": "Artificial yellow colour", "unit": "mg", "direction": "lower_is_better", "daily_value": None, "group": None},
            {"id": "caffeine_mg", "label": "Caffeine", "unit": "mg", "direction": "lower_is_better", "daily_value": 400, "group": None},
        ],
        "mechanisms": {
            "aroma_sweetness_enhancement": {
                "label": "Aroma can suggest sweetness",
                "plain_text": "Some aromatic compounds are reported to make a food taste sweeter without adding sugar.",
            },
            "umami_synergy": {
                "label": "Umami can stand in for saltiness",
                "plain_text": "Glutamate-rich foods are reported to boost savory taste, which can make a dish seem saltier.",
            },
            "acid_brightness": {
                "label": "Acid can brighten flavor",
                "plain_text": "A little acid is reported to brighten flavor so a dish needs less salt or sugar to taste vivid.",
            },
            "emulsion_mouthfeel": {
                "label": "An emulsion can restore creaminess",
                "plain_text": "A smooth emulsion is reported to restore some of the creamy mouthfeel that fat usually provides.",
            },
            "moisture_body": {
                "label": "Moisture can restore body",
                "plain_text": "Extra moisture and a softer texture are reported to bring back some of the body lost when fat is reduced.",
            },
            "salt_substitute": {
                "label": "A salt stand-in",
                "plain_text": "Potassium chloride is reported to taste salty, with a bitter edge for some people.",
            },
        },
    }


# Extra fields for ingredients that already exist. Sweet, salty, sugar, sodium,
# fat, molecules, fits, max_g, and caution are copied from the old file.
# richness is omitted on purpose for plain fat sources: it is set equal to fat_g.
OLD_EXTRA = {
    "sugar": dict(display_name="Sugar", aliases=["white_sugar", "granulated_sugar"], category="sweetener", role="sweetener", protein=0.0, carbs=1.0, sat=0.0, fiber=0.0, cholesterol=0.0),
    "salt": dict(display_name="Salt", aliases=["table_salt"], category="seasoning", role="seasoning", protein=0.0, carbs=0.0, sat=0.0, fiber=0.0, cholesterol=0.0),
    "butter": dict(display_name="Butter", aliases=["unsalted_butter"], category="dairy", role="fat_source", protein=0.009, carbs=0.006, sat=0.51, fiber=0.0, cholesterol=2.15),
    "heavy_cream": dict(display_name="Heavy cream", aliases=["cream", "whipping_cream"], category="dairy", role="fat_source", protein=0.021, carbs=0.03, sat=0.23, fiber=0.0, cholesterol=1.1),
    "lemon_juice": dict(display_name="Lemon juice", aliases=["lemon"], category="fruit", role="liquid", protein=0.004, carbs=0.069, sat=0.0, fiber=0.003, cholesterol=0.0),
    "tomato": dict(display_name="Tomato", aliases=["fresh_tomato"], category="vegetable", role="structural", protein=0.009, carbs=0.039, sat=0.0, fiber=0.012, cholesterol=0.0, umami=0.04),
    "onion": dict(display_name="Onion", aliases=["onion_bulb"], category="vegetable", role="aromatic", protein=0.011, carbs=0.093, sat=0.0, fiber=0.017, cholesterol=0.0),
    "garlic": dict(display_name="Garlic", aliases=["garlic_clove"], category="vegetable", role="aromatic", protein=0.064, carbs=0.33, sat=0.0, fiber=0.021, cholesterol=0.0),
    "chicken_breast": dict(display_name="Chicken breast", aliases=["chicken"], category="protein", role="structural", protein=0.31, carbs=0.0, sat=0.01, fiber=0.0, cholesterol=0.85, umami=0.06),
    "vegetable_oil": dict(display_name="Vegetable oil", aliases=["oil", "cooking_oil"], category="oil", role="fat_source", protein=0.0, carbs=0.0, sat=0.14, fiber=0.0, cholesterol=0.0),
    "garam_masala": dict(display_name="Garam masala", aliases=["garam"], category="spice", role="aromatic", protein=0.11, carbs=0.45, sat=0.015, fiber=0.2, cholesterol=0.0),
    "chili_powder": dict(display_name="Chili powder", aliases=["chilli_powder", "red_chili_powder"], category="spice", role="aromatic", protein=0.13, carbs=0.5, sat=0.025, fiber=0.34, cholesterol=0.0),
    "water": dict(display_name="Water", aliases=["plain_water"], category="liquid", role="liquid", protein=0.0, carbs=0.0, sat=0.0, fiber=0.0, cholesterol=0.0),
    "green_bell_pepper": dict(display_name="Green bell pepper", aliases=["bell_pepper", "capsicum"], category="vegetable", role="aromatic", protein=0.009, carbs=0.046, sat=0.0, fiber=0.017, cholesterol=0.0),
    "vanilla_extract": dict(display_name="Vanilla extract", aliases=["vanilla", "vanilla_essence"], category="spice", role="aromatic", protein=0.001, carbs=0.13, sat=0.0, fiber=0.0, cholesterol=0.0, mechanism="aroma_sweetness_enhancement"),
    "cinnamon": dict(display_name="Cinnamon", aliases=["cassia", "cinnamon_powder"], category="spice", role="aromatic", protein=0.04, carbs=0.55, sat=0.003, fiber=0.53, cholesterol=0.0, mechanism="aroma_sweetness_enhancement"),
    "mint_leaves": dict(display_name="Mint leaves", aliases=["mint", "pudina"], category="herb", role="aromatic", protein=0.033, carbs=0.08, sat=0.0, fiber=0.07, cholesterol=0.0, mechanism="aroma_sweetness_enhancement"),
    "tomato_paste": dict(display_name="Tomato paste", aliases=["concentrated_tomato"], category="vegetable", role="condiment", protein=0.043, carbs=0.19, sat=0.001, fiber=0.04, cholesterol=0.0, umami=0.45, mechanism="umami_synergy", extra_axes=["umami"]),
    "mushroom_powder": dict(display_name="Mushroom powder", aliases=["dried_mushroom_powder"], category="vegetable", role="seasoning", protein=0.22, carbs=0.3, sat=0.004, fiber=0.12, cholesterol=0.0, umami=0.8, mechanism="umami_synergy", extra_axes=["umami"]),
    "lemon_zest": dict(display_name="Lemon zest", aliases=["zest", "lemon_peel"], category="fruit", role="aromatic", protein=0.015, carbs=0.16, sat=0.0, fiber=0.11, cholesterol=0.0, mechanism="acid_brightness"),
    "potassium_chloride": dict(display_name="Potassium chloride", aliases=["kcl", "salt_substitute"], category="seasoning", role="seasoning", protein=0.0, carbs=0.0, sat=0.0, fiber=0.0, cholesterol=0.0, mechanism="salt_substitute"),
    "yogurt": dict(display_name="Yogurt", aliases=["plain_yogurt", "dahi"], category="dairy", role="condiment", protein=0.035, carbs=0.047, sat=0.021, fiber=0.0, cholesterol=0.13, richness=0.2, mechanism="emulsion_mouthfeel"),
    "applesauce": dict(display_name="Applesauce", aliases=["apple_sauce"], category="fruit", role="condiment", protein=0.002, carbs=0.14, sat=0.0, fiber=0.012, cholesterol=0.0, richness=0.15, mechanism="moisture_body"),
    "stock_reduction": dict(display_name="Stock reduction", aliases=["reduced_stock"], category="liquid", role="liquid", protein=0.05, carbs=0.02, sat=0.003, fiber=0.0, cholesterol=0.02, umami=0.5, richness=0.18, mechanism="moisture_body", extra_axes=["umami"]),
}


def _migrate_old_ingredient(name: str, old: dict) -> dict:
    """Turn one old ingredient into a v2 row without changing its taste math."""
    spec = OLD_EXTRA[name]
    fat = old["fat_g_per_g"]
    sugar = old["sugar_g_per_g"]
    # Plain fat sources taste as rich as they are fatty. Compensators instead
    # carry a small richness number, because that number is a taste boost
    # from their mechanism (the same idea as mushroom powder's salty 0.6).
    if "richness" in spec:
        richness = spec["richness"]
    elif spec["role"] == "fat_source":
        richness = fat
    else:
        richness = 0.0
    nutrients = _macros(
        spec["protein"], spec["carbs"], fat, sugar, spec["sat"], spec["fiber"], spec["cholesterol"]
    )
    chemicals = {"sodium_mg": old["sodium_mg_per_g"]}
    chemicals.update(spec.get("chemicals", {}))
    taste = {
        "sweet": old["sweet_equiv_per_g"],
        "salty": old["salty_equiv_per_g"],
        "umami": spec.get("umami", 0.0),
        "richness": richness,
    }
    compensator = None
    if "compensator_for" in old:
        compensates = [AXIS_RENAME.get(item, item) for item in old["compensator_for"]]
        for extra in spec.get("extra_axes", []):
            if extra not in compensates:
                compensates.append(extra)
        compensator = {
            "compensates": compensates,
            "fits": list(old["fits"]),
            "max_g": old["max_g"],
            "mechanism": spec["mechanism"],
            "caution": old.get("caution"),
        }
    row = _ingredient(
        spec["display_name"], spec["aliases"], spec["category"], spec["role"],
        nutrients, chemicals, taste, old.get("molecules", []), compensator,
    )
    # Guards: the numbers the current tests depend on must be the same object values.
    if row["taste_per_g"]["sweet"] != old["sweet_equiv_per_g"]:
        raise ValueError(name)
    if row["taste_per_g"]["salty"] != old["salty_equiv_per_g"]:
        raise ValueError(name)
    if row["nutrients_per_g"]["sugar_g"] != old["sugar_g_per_g"]:
        raise ValueError(name)
    if row["nutrients_per_g"]["fat_g"] != old["fat_g_per_g"]:
        raise ValueError(name)
    if row["chemicals_per_g"].get("sodium_mg", 0.0) != old["sodium_mg_per_g"]:
        raise ValueError(name)
    return row


def _new_ingredient(
    name: str,
    display_name: str,
    aliases: list[str],
    category: str,
    role: str,
    protein: float,
    carbs: float,
    fat: float,
    sugar: float = 0.0,
    sat: float = 0.0,
    fiber: float = 0.0,
    cholesterol: float = 0.0,
    chemicals: dict | None = None,
    sweet: float = 0.0,
    salty: float = 0.0,
    umami: float = 0.0,
    richness: float | None = None,
    molecules: list[str] | None = None,
    compensates: list[str] | None = None,
    fits: list[str] | None = None,
    max_g: float | None = None,
    mechanism: str | None = None,
    caution: str | None = None,
) -> tuple[str, dict]:
    """Build one brand-new ingredient. Richness defaults to fat_g for fat sources."""
    if richness is None:
        richness = fat if role == "fat_source" else 0.0
    nutrients = _macros(protein, carbs, fat, sugar, sat, fiber, cholesterol)
    taste = {"sweet": sweet, "salty": salty, "umami": umami, "richness": richness}
    compensator = None
    if compensates is not None:
        compensator = {
            "compensates": list(compensates),
            "fits": list(fits or []),
            "max_g": max_g,
            "mechanism": mechanism,
            "caution": caution,
        }
    return name, _ingredient(
        display_name, aliases, category, role, nutrients,
        chemicals or {}, taste, molecules or [], compensator,
    )


def _new_ingredients() -> dict[str, dict]:
    """Ingredients that were not in the original file.

    Packaged rows (seasoning sachet, ham, cocoa) exist so the Chemicals
    module has MSG, preservatives, colour, and caffeine to show.
    New compensators avoid the tags of lemonade, tomato soup, and butter
    chicken unless their axis cannot change those dishes' current picks.
    """
    rows = [
        _new_ingredient("flour", "Flour", ["all_purpose_flour", "maida", "wheat_flour"], "grain", "structural", protein=0.1, carbs=0.76, fat=0.01, sugar=0.003, sat=0.002, fiber=0.03, chemicals={"sodium_mg": 0.02}, sweet=0.01, molecules=["starch"]),
        _new_ingredient("cocoa_powder", "Cocoa powder", ["cocoa", "unsweetened_cocoa"], "spice", "aromatic", protein=0.2, carbs=0.58, fat=0.14, sugar=0.015, sat=0.08, fiber=0.33, chemicals={"sodium_mg": 0.21, "caffeine_mg": 2.3}, sweet=0.04, umami=0.08, richness=0.12, molecules=["theobromine", "caffeine", "phenylacetaldehyde"]),
        _new_ingredient("egg", "Egg", ["whole_egg", "chicken_egg"], "protein", "structural", protein=0.13, carbs=0.01, fat=0.1, sugar=0.01, sat=0.03, cholesterol=3.7, chemicals={"sodium_mg": 1.4}, sweet=0.01, salty=0.02, umami=0.04, richness=0.08, molecules=["diacetyl"]),
        _new_ingredient("milk", "Milk", ["whole_milk"], "dairy", "liquid", protein=0.033, carbs=0.048, fat=0.033, sugar=0.048, sat=0.02, cholesterol=0.14, chemicals={"sodium_mg": 0.44}, sweet=0.03, salty=0.01, umami=0.01, richness=0.03, molecules=["diacetyl", "lactose"]),
        _new_ingredient("baking_powder", "Baking powder", ["leavening_powder"], "seasoning", "seasoning", protein=0.0, carbs=0.28, fat=0.0, chemicals={"sodium_mg": 90.0}, salty=0.05, molecules=[]),
        _new_ingredient("olive_oil", "Olive oil", ["extra_virgin_olive_oil"], "oil", "fat_source", protein=0.0, carbs=0.0, fat=1.0, sat=0.14, molecules=["oleic_acid", "squalene"]),
        _new_ingredient("parmesan", "Parmesan", ["parmesan_cheese", "parmigiano"], "dairy", "condiment", protein=0.35, carbs=0.04, fat=0.26, sat=0.16, cholesterol=0.8, chemicals={"sodium_mg": 15.0}, sweet=0.01, salty=0.2, umami=0.7, richness=0.2, molecules=["glutamic_acid", "butyric_acid"], compensates=["umami"], fits=["salad", "sauce", "pasta", "sandwich"], max_g=15, mechanism="umami_synergy"),
        _new_ingredient("anchovy", "Anchovy", ["anchovy_fillet"], "protein", "condiment", protein=0.29, carbs=0.0, fat=0.1, sat=0.02, cholesterol=0.85, chemicals={"sodium_mg": 36.0}, salty=0.25, umami=0.6, richness=0.08, molecules=["glutamic_acid", "inosinic_acid"]),
        _new_ingredient("dijon_mustard", "Dijon mustard", ["mustard", "dijon"], "condiment", "condiment", protein=0.04, carbs=0.05, fat=0.04, sugar=0.02, sat=0.002, chemicals={"sodium_mg": 11.0}, sweet=0.02, salty=0.12, umami=0.05, richness=0.02, molecules=["allyl_isothiocyanate"]),
        _new_ingredient("black_pepper", "Black pepper", ["ground_black_pepper", "pepper"], "spice", "aromatic", protein=0.1, carbs=0.64, fat=0.03, sugar=0.006, sat=0.01, fiber=0.25, chemicals={"sodium_mg": 0.2}, salty=0.02, molecules=["piperine"]),
        _new_ingredient("bread", "Bread", ["white_bread", "sandwich_bread"], "grain", "structural", protein=0.09, carbs=0.49, fat=0.03, sugar=0.05, sat=0.007, fiber=0.027, chemicals={"sodium_mg": 4.9}, sweet=0.02, salty=0.04, umami=0.02, richness=0.02, molecules=["maltol"]),
        _new_ingredient("ham", "Ham", ["cooked_ham", "ham_slice"], "protein", "structural", protein=0.16, carbs=0.02, fat=0.09, sugar=0.015, sat=0.03, cholesterol=0.55, chemicals={"sodium_mg": 12.0, "sodium_nitrite_mg": 0.12}, sweet=0.01, salty=0.15, umami=0.12, richness=0.05, molecules=["glutamic_acid"]),
        _new_ingredient("cheddar", "Cheddar", ["cheddar_cheese"], "dairy", "fat_source", protein=0.23, carbs=0.02, fat=0.33, sugar=0.005, sat=0.21, cholesterol=1.0, chemicals={"sodium_mg": 6.5}, sweet=0.01, salty=0.08, umami=0.15, molecules=["butyric_acid", "diacetyl"]),
        _new_ingredient("instant_noodle_cake", "Instant noodle cake", ["ramen_cake", "noodle_block"], "grain", "structural", protein=0.1, carbs=0.62, fat=0.16, sugar=0.02, sat=0.07, fiber=0.03, chemicals={"sodium_mg": 2.5}, sweet=0.01, salty=0.03, umami=0.02, richness=0.12, molecules=["starch"]),
        _new_ingredient("seasoning_sachet", "Seasoning sachet", ["seasoning_packet", "flavour_sachet"], "packaged", "seasoning", protein=0.08, carbs=0.35, fat=0.04, sugar=0.12, sat=0.02, fiber=0.02, chemicals={"sodium_mg": 180.0, "msg_g": 0.2, "sodium_benzoate_mg": 0.4, "tartrazine_mg": 3.0}, sweet=0.08, salty=0.5, umami=0.3, molecules=["glutamic_acid"]),
        _new_ingredient("palm_oil", "Palm oil", ["palm_fat"], "oil", "fat_source", protein=0.0, carbs=0.0, fat=1.0, sat=0.49, molecules=["palmitic_acid", "oleic_acid"]),
        _new_ingredient("turmeric", "Turmeric", ["haldi", "ground_turmeric"], "spice", "aromatic", protein=0.08, carbs=0.67, fat=0.1, sugar=0.03, sat=0.03, fiber=0.21, chemicals={"sodium_mg": 0.38}, sweet=0.02, salty=0.01, umami=0.02, molecules=["curcumin"]),
        _new_ingredient("cumin", "Cumin", ["jeera", "ground_cumin"], "spice", "aromatic", protein=0.18, carbs=0.44, fat=0.22, sugar=0.02, sat=0.015, fiber=0.11, chemicals={"sodium_mg": 1.68}, sweet=0.02, salty=0.01, umami=0.03, molecules=["cuminaldehyde"]),
        _new_ingredient("coriander_powder", "Coriander powder", ["ground_coriander", "dhania"], "spice", "aromatic", protein=0.12, carbs=0.55, fat=0.18, sugar=0.0, sat=0.01, fiber=0.4, chemicals={"sodium_mg": 0.35}, sweet=0.03, umami=0.02, molecules=["linalool"]),
        _new_ingredient("ginger", "Ginger", ["ginger_root", "fresh_ginger"], "spice", "aromatic", protein=0.018, carbs=0.18, fat=0.008, sugar=0.017, sat=0.002, fiber=0.02, chemicals={"sodium_mg": 0.13}, sweet=0.03, umami=0.01, molecules=["gingerol", "zingiberene"]),
        _new_ingredient("soy_sauce", "Soy sauce", ["soya_sauce", "shoyu"], "condiment", "condiment", protein=0.08, carbs=0.05, fat=0.001, sugar=0.01, chemicals={"sodium_mg": 55.0}, sweet=0.04, salty=0.5, umami=0.55, richness=0.01, molecules=["glutamic_acid"], compensates=["umami", "salty"], fits=["noodle", "stir_fry", "sandwich"], max_g=10, mechanism="umami_synergy", caution="Very high in sodium, so it gives sodium back while it restores savoriness."),
        _new_ingredient("honey", "Honey", ["liquid_honey"], "sweetener", "sweetener", protein=0.003, carbs=0.82, fat=0.0, sugar=0.82, chemicals={"sodium_mg": 0.04}, sweet=0.85, molecules=["fructose", "glucose"]),
        _new_ingredient("egg_yolk", "Egg yolk", ["egg_yolks"], "protein", "fat_source", protein=0.16, carbs=0.04, fat=0.27, sugar=0.005, sat=0.09, cholesterol=10.8, chemicals={"sodium_mg": 0.48}, sweet=0.01, salty=0.02, umami=0.05, molecules=["diacetyl"]),
        _new_ingredient("cardamom", "Cardamom", ["elaichi", "ground_cardamom"], "spice", "aromatic", protein=0.11, carbs=0.68, fat=0.07, sat=0.01, fiber=0.28, chemicals={"sodium_mg": 0.18}, sweet=0.4, molecules=["cineole", "linalool", "limonene"], compensates=["sweet"], fits=["dessert", "baking", "curry"], max_g=2, mechanism="aroma_sweetness_enhancement"),
        _new_ingredient("nutritional_yeast", "Nutritional yeast", ["nooch"], "seasoning", "seasoning", protein=0.5, carbs=0.35, fat=0.05, sat=0.01, fiber=0.2, chemicals={"sodium_mg": 2.0}, sweet=0.05, salty=0.05, umami=0.55, richness=0.02, molecules=["glutamic_acid"], compensates=["umami"], fits=["sauce", "pasta", "salad", "sandwich"], max_g=10, mechanism="umami_synergy"),
        _new_ingredient("silken_tofu", "Silken tofu", ["soft_tofu", "silken_bean_curd"], "protein", "structural", protein=0.05, carbs=0.02, fat=0.025, sugar=0.005, sat=0.005, chemicals={"sodium_mg": 0.12}, sweet=0.01, salty=0.01, umami=0.03, richness=0.12, molecules=[], compensates=["richness"], fits=["curry", "soup", "sauce", "dressing"], max_g=80, mechanism="emulsion_mouthfeel"),
        _new_ingredient("miso", "Miso", ["miso_paste"], "condiment", "condiment", protein=0.12, carbs=0.25, fat=0.06, sugar=0.06, sat=0.01, fiber=0.05, chemicals={"sodium_mg": 37.0}, sweet=0.05, salty=0.4, umami=0.65, richness=0.04, molecules=["glutamic_acid"], compensates=["umami"], fits=["soup", "stew", "sauce"], max_g=15, mechanism="umami_synergy", caution="High in sodium, so it gives sodium back while it restores savoriness."),
        _new_ingredient("cornstarch", "Cornstarch", ["cornflour"], "grain", "thickener", protein=0.003, carbs=0.91, fat=0.001, chemicals={"sodium_mg": 0.09}, sweet=0.01, molecules=["starch"]),
        _new_ingredient("vinegar", "Vinegar", ["white_vinegar"], "condiment", "condiment", protein=0.0, carbs=0.004, fat=0.0, sugar=0.004, chemicals={"sodium_mg": 0.02}, sweet=0.005, umami=0.01, molecules=["acetic_acid"]),
    ]
    return dict(rows)


def _dishes(old_dishes: dict) -> dict:
    """Keep the original three recipes gram-for-gram, then add the five new ones."""
    meta = {
        "lemonade": ("Lemonade", 4, ["lemon_juice"]),
        "tomato_soup": ("Tomato soup", 4, ["tomato"]),
        "butter_chicken": ("Butter chicken", 4, ["chicken_breast"]),
    }
    dishes = {}
    for slug, (display_name, servings, core) in meta.items():
        old = old_dishes[slug]
        dishes[slug] = {
            "display_name": display_name,
            "servings": servings,
            "tags": list(old["tags"]),
            "ingredients": dict(old["ingredients"]),
            "core_ingredients": core,
        }
    dishes["chicken_curry"] = {
        "display_name": "Chicken curry",
        "servings": 4,
        "tags": ["curry", "stew"],
        "ingredients": {
            "chicken_breast": 450,
            "onion": 150,
            "tomato": 200,
            "garlic": 12,
            "ginger": 15,
            "vegetable_oil": 25,
            "salt": 8,
            "turmeric": 3,
            "cumin": 3,
            "coriander_powder": 3,
            "chili_powder": 4,
            "water": 250,
        },
        "core_ingredients": ["chicken_breast"],
    }
    dishes["chocolate_cake"] = {
        "display_name": "Chocolate cake",
        "servings": 8,
        "tags": ["dessert", "baking"],
        "ingredients": {
            "flour": 180,
            "sugar": 150,
            "cocoa_powder": 40,
            "butter": 100,
            "egg": 100,
            "milk": 120,
            "baking_powder": 6,
            "salt": 2,
        },
        "core_ingredients": ["flour", "cocoa_powder"],
    }
    dishes["caesar_dressing"] = {
        "display_name": "Caesar dressing",
        "servings": 4,
        "tags": ["salad", "dressing"],
        "ingredients": {
            "olive_oil": 80,
            "egg_yolk": 30,
            "parmesan": 30,
            "lemon_juice": 20,
            "garlic": 4,
            "anchovy": 10,
            "dijon_mustard": 8,
            "salt": 2,
            "black_pepper": 1,
        },
        "core_ingredients": ["parmesan", "anchovy"],
    }
    dishes["instant_noodles"] = {
        "display_name": "Instant noodles",
        "servings": 1,
        "tags": ["noodle", "packaged"],
        "ingredients": {
            "instant_noodle_cake": 75,
            "seasoning_sachet": 8,
            "palm_oil": 4,
            "water": 400,
        },
        "core_ingredients": ["instant_noodle_cake"],
    }
    dishes["ham_cheese_sandwich"] = {
        "display_name": "Ham and cheese sandwich",
        "servings": 1,
        "tags": ["sandwich", "bread"],
        "ingredients": {
            "bread": 80,
            "ham": 50,
            "cheddar": 30,
            "butter": 8,
            "dijon_mustard": 8,
        },
        "core_ingredients": ["bread", "ham"],
    }
    return dishes


def _check(catalog: dict, old: dict) -> None:
    """Stop before writing if the catalog would fail its own rules."""
    ingredients = catalog["ingredients"]
    if not 45 <= len(ingredients) <= 60:
        raise SystemExit(f"ingredient count {len(ingredients)} is outside 45–60")
    seen_aliases: dict[str, str] = {}
    counts = {"sweet": 0, "salty": 0, "umami": 0, "richness": 0}
    for name, ing in ingredients.items():
        for alias in ing["aliases"]:
            if alias in seen_aliases or alias in ingredients:
                raise SystemExit(f"alias {alias!r} on {name} collides with {seen_aliases.get(alias, alias)}")
            seen_aliases[alias] = name
        nutrients = ing["nutrients_per_g"]
        expected = 4 * nutrients["protein_g"] + 4 * nutrients["carbs_g"] + 9 * nutrients["fat_g"]
        calories = nutrients["calories_kcal"]
        if expected == 0:
            if calories != 0:
                raise SystemExit(f"{name} calories should be 0")
        elif abs(calories - expected) / expected > 0.20:
            raise SystemExit(f"{name} calories {calories} vs {expected}")
        comp = ing.get("compensator")
        if comp:
            for axis in comp["compensates"]:
                counts[axis] += 1
    for axis, minimum in (("sweet", 4), ("salty", 4), ("richness", 4), ("umami", 3)):
        if counts[axis] < minimum:
            raise SystemExit(f"only {counts[axis]} compensators for {axis}")
    for slug, dish in catalog["dishes"].items():
        for ing_name in dish["ingredients"]:
            if ing_name not in ingredients:
                raise SystemExit(f"{slug} uses missing ingredient {ing_name}")
        for core in dish["core_ingredients"]:
            if core not in dish["ingredients"]:
                raise SystemExit(f"{slug} core {core} is not in the dish")
    # The three original recipes stay gram-for-gram.
    for slug, dish in old["dishes"].items():
        if catalog["dishes"][slug]["ingredients"] != dish["ingredients"]:
            raise SystemExit(f"{slug} grams changed")
        if catalog["dishes"][slug]["tags"] != dish["tags"]:
            raise SystemExit(f"{slug} tags changed")
    if ingredients["mushroom_powder"]["taste_per_g"]["salty"] != 0.6:
        raise SystemExit("mushroom salty drift")
    if ingredients["vanilla_extract"]["compensator"]["max_g"] != 3:
        raise SystemExit("vanilla cap drift")
    print(f"ingredients={len(ingredients)} dishes={len(catalog['dishes'])} compensators={counts}")


def build(old: dict) -> dict:
    """Migrate old rows, then add the new catalog around them."""
    if set(old["ingredients"]) != set(OLD_EXTRA):
        missing = set(old["ingredients"]) - set(OLD_EXTRA)
        extra = set(OLD_EXTRA) - set(old["ingredients"])
        raise SystemExit(f"old ingredient set mismatch missing={missing} extra={extra}")
    catalog = _defs()
    ingredients = {name: _migrate_old_ingredient(name, ing) for name, ing in old["ingredients"].items()}
    ingredients.update(_new_ingredients())
    catalog["ingredients"] = ingredients
    catalog["dishes"] = _dishes(old["dishes"])
    return catalog


def main() -> None:
    old = json.loads(DATA_PATH.read_text())
    if old.get("meta", {}).get("schema_version") == 2:
        print("already schema_version 2; left the file unchanged")
        return
    catalog = build(old)
    _check(catalog, old)
    DATA_PATH.write_text(json.dumps(catalog, indent=2) + "\n")
    print(f"wrote {DATA_PATH}")


if __name__ == "__main__":
    main()
