"""Generate foods_draft.csv from the curated raw/ CSVs and food_categories.csv.

base_unit assignment was reviewed by batch for the 5 groups flagged as most uncertain
(Leche y postres, Grasas, Aderezos, Caldos y sopas, Postres industriales) — see
docs/plans/food-catalog.md, Stage 2. `potes` was dropped from the unit set entirely
per that review (final enum: unidades/kilogramos/litros) since it added variety
without a real distinction: anything sold by weight, including packaged single-serve
items (yogurt cups, flan, ice cream), goes to kilogramos; only genuinely pourable
liquids go to litros.
"""

import csv
import re
import unicodedata
from pathlib import Path

BASE = Path(__file__).parent
REFERENCE_DATA = BASE.parent.parent / "app" / "reference_data"
RAW = BASE / "raw"
OUTPUT = BASE / "foods_draft.csv"

EXCLUDE_RAW_FILES = {
    "_blank_values.csv",
    "_nutrient_normalization_map.csv",
    "_review_irregulares.csv",
}

# Individual foods excluded from the catalog at curation time (Stage 2) — kept in
# raw/ (a faithful extraction of SARA2) but dropped here since they don't belong
# in a catalog of food an establishment can receive as stock.
EXCLUDED_NAMES = {
    # not something an establishment receives as donated/purchased stock
    "Leche materna",
}

# SARA 2's own group numbering (raw/*.csv's `grupo_num`) mapped to this
# catalog's `food_categories.code`. Lives here, not in
# app/reference_data/food_categories.csv, because the app's own schema has no
# use for the source's group number beyond this one-time extraction step.
GROUP_NUM_TO_CATEGORY = {
    1: "verduras",
    2: "frutas",
    3: "legumbres_cereales_papa_choclo_batata_pan_y_pastas",
    4: "leche_y_postres_de_leche",
    5: "yogures",
    6: "quesos",
    7: "carnes",
    8: "huevos",
    9: "pescados_y_mariscos",
    10: "aceites",
    11: "frutas_secas_y_semillas",
    12: "azucares_mermeladas_y_dulces",
    13: "golosinas_y_chocolates",
    14: "grasas",
    15: "snacks_salados",
    16: "aderezos",
    17: "caldos_y_sopas_industriales",
    18: "postres_industriales_y_helados",
    19: "sales",
    20: "bebidas_con_azucar",
    21: "bebidas_sin_azucar",
    22: "bebidas_alcoholicas_y_energizantes",
    24: "infusiones",
    25: "alimentos_de_locales_de_comidas_rapidas",
}

GROUP_DEFAULT_UNIT = {
    "verduras": "kilogramos",
    "frutas": "kilogramos",
    "legumbres_cereales_papa_choclo_batata_pan_y_pastas": "kilogramos",
    "leche_y_postres_de_leche": "litros",
    "yogures": "kilogramos",
    "quesos": "kilogramos",
    "carnes": "kilogramos",
    "huevos": "unidades",
    "pescados_y_mariscos": "kilogramos",
    "aceites": "litros",
    "frutas_secas_y_semillas": "kilogramos",
    "azucares_mermeladas_y_dulces": "kilogramos",
    "golosinas_y_chocolates": "kilogramos",
    "grasas": "kilogramos",
    "snacks_salados": "kilogramos",
    "aderezos": "kilogramos",
    "caldos_y_sopas_industriales": "kilogramos",
    "postres_industriales_y_helados": "kilogramos",
    "sales": "kilogramos",
    "bebidas_con_azucar": "litros",
    "bebidas_sin_azucar": "litros",
    "bebidas_alcoholicas_y_energizantes": "litros",
    "infusiones": "kilogramos",
    "alimentos_de_locales_de_comidas_rapidas": "unidades",
}

# Exact-name overrides for cases too specific/inconsistent for a keyword regex,
# decided by hand during the Stage 2 base_unit review. Checked before OVERRIDES.
NAME_OVERRIDES = {
    # sold by weight (can/sachet), not a pourable liquid
    "Leche condensada": "kilogramos",
    # pourable liquid cream, unlike butter/margarina
    "Crema de leche": "litros",
    # bottled pourable liquid, unlike the other paste-like sauces
    "Salsa de soja": "litros",
    "Aderezo Caesar o Ranch": "litros",  # bottled pourable dressing
    "Aderezo para ensaladas light": "litros",  # bottled pourable dressing
    # single-serve cup, weighed not poured
    "Flan envasado listo para consumir": "kilogramos",
    "Flan light envasado listo para consumir": "kilogramos",
    "Postre de leche listo para consumir tipo Danonino": "kilogramos",
    "Postre de leche listo para consumir tipo Serenito": "kilogramos",
    "Postre light de leche listo para consumir": "kilogramos",
    "Probióticos descremados": "kilogramos",
    "Probióticos enteros": "kilogramos",
    # aerosol cooking oil spray, same criteria as Crema chantilly
    "Rocío vegetal": "kilogramos",
    # almond milk, a drinkable liquid
    "Alimento a base de almendras (leche de almendras)": "litros",
    # False positives from OVERRIDES below: the keyword appears in the name but
    # doesn't describe a liquid/counted ingredient of the food itself.
    "Fideos frescos, al huevo, crudos": "kilogramos",  # egg pasta, not eggs
    "Fideos frescos, al huevo, hervidos": "kilogramos",
    # "huevos" is a recipe ingredient
    "Pan paraguayo / galleta paraguaya (bollitos con levadura, harina, grasa o "
    "manteca, leche, huevos y anís)": "kilogramos",
    # explicitly has no oil
    "Pan francés o pan casero sin agregado de grasa o aceite": "kilogramos",
    # solid fish, oil is just the packing medium
    "Anchoa, enlatada en aceite": "kilogramos",
    "Atún, enlatado en aceite": "kilogramos",
    "Merluza, enlatada en agua y aceite": "kilogramos",
    "Sardinas, enlatadas en aceite": "kilogramos",
    # a cracker type, not water
    "Galletitas de agua con girasol alto oleico": "kilogramos",
    "Galletitas de agua con grasa vacuna": "kilogramos",
    "Galletitas de agua light": "kilogramos",
    "Galletitas de agua sin sal": "kilogramos",
    "Galletitas de agua sin sal con chía y lino": "kilogramos",
    "Galletitas de agua, PROMEDIO": "kilogramos",
    # a cookie; "de vino" is the flavor, not the content
    "Rosquito de vino (cuyano)": "kilogramos",
}

# (regex, unit), checked in order, first match wins. Applied case-insensitively
# against the food name. "helado" must precede the agua/bebida group: "Helado de
# agua" is a type of ice cream (water-based, as opposed to crema-based), not a
# liquid ingredient — the whole subcategory (heladería, palito, envasado, cucurucho,
# bombón) is sold and weighed by kg, per the Stage 2 review.
OVERRIDES = [
    (r"huevo", "unidades"),
    (r"helado", "kilogramos"),
    (r"bebible", "litros"),
    (r"\bleche\b.*\bfluida\b|\bleche\b.*\bordeñada\b|\bleche de vaca\b", "litros"),
    (r"\baceite\b", "litros"),
    (r"^vinagre\b|^aceto balsámico\b", "litros"),
    (r"en polvo|polvo\b", "kilogramos"),
    (
        r"\bagua\b|\bjugo\b|\bbebida\b|\bgaseosa\b|\bcerveza\b|\bvino\b|\bfernet\b|\blicor\b",
        "litros",
    ),
    (r"\bsal\b|\bsales\b", "kilogramos"),
]


def slugify(name: str) -> str:
    n = unicodedata.normalize("NFKD", name)
    n = n.encode("ascii", "ignore").decode("ascii")
    n = n.lower()
    n = re.sub(r"[^a-z0-9]+", "_", n)
    return re.sub(r"_+", "_", n).strip("_")


def assign_base_unit(name: str, category: str) -> tuple[str, str]:
    if name in NAME_OVERRIDES:
        return NAME_OVERRIDES[name], "__name_override__"
    for pattern, unit in OVERRIDES:
        if re.search(pattern, name, re.IGNORECASE):
            return unit, pattern
    return GROUP_DEFAULT_UNIT[category], ""


def main() -> None:
    # alimento -> (category, max source page) per group, in first-seen order
    foods: dict[str, tuple[str, int]] = {}
    order: list[str] = []
    for path in sorted(RAW.iterdir()):
        if path.name in EXCLUDE_RAW_FILES or not path.name.endswith(".csv"):
            continue
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                group_num = int(row["grupo_num"])
                category = GROUP_NUM_TO_CATEGORY[group_num]
                name = row["alimento"]
                if name in EXCLUDED_NAMES:
                    continue
                page = int(row["pagina_pdf"])
                if name not in foods:
                    foods[name] = (category, page)
                    order.append(name)
                else:
                    cat, max_page = foods[name]
                    foods[name] = (cat, max(max_page, page))

    codes_seen: dict[str, int] = {}
    rows = []
    for name in order:
        category, source_page = foods[name]
        base_unit, override_applied = assign_base_unit(name, category)
        code = slugify(name)
        codes_seen[code] = codes_seen.get(code, 0) + 1
        if codes_seen[code] > 1:
            code = f"{code}_{codes_seen[code]}"
        rows.append(
            {
                "code": code,
                "name": name,
                "category": category,
                "base_unit": base_unit,
                "source_page": source_page,
                "override_applied": override_applied,
            }
        )

    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "code",
                "name",
                "category",
                "base_unit",
                "source_page",
                "override_applied",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUTPUT}")


if __name__ == "__main__":
    main()
