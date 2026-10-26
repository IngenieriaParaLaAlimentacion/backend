# ADR-0027: Sources and criteria for the food equivalences seed

- **Status**: Accepted
- **Date**: 2026-10-26
- **Deciders**: Backend team
- **Related**: Issue #193 (equivalence data), ADR-0010, ADR-0011, ADR-0012, ADR-0025

## Context

ADR-0025 created the `food_equivalences` table and the conversion module, and left the table empty: no row means no equivalence, never a default value. Until the table holds real data, every food stocked in `litros` or `unidades` is left out of the nutrition service and the recipes with a warning, and a receipt line printed in another unit than the food's base unit cannot be prefilled.

SARA 2 gives nutrients per 100 g of edible portion, in the raw state, and nothing else: it has no densities and no unit weights. The factors have to come from another source, and each value has to say where it comes from and how close the match is.

## Decision

### Sources

| | FAO/INFOODS Density Database v2.0 | UBA weight/volume table |
| --- | --- | --- |
| What it gives | Density and specific gravity of 638 foods, in English | Weight per unit of Argentine foods and products, in Spanish |
| Used for | `density_g_ml` (139 rows) | `unit_weight_g` (32 rows) |
| Reference | Charrondière UR, Haytowitz D, Stadlmayr B. *FAO/INFOODS Density Database Version 2.0*. Rome: FAO; 2012. E-ISBN 978-92-5-107346-9. <http://www.fao.org/4/ap815e/ap815e.pdf> | *Medidas, equivalencias y porciones de alimentos* (`Peso-Volumen-Medidas fmed.pdf`), which complements Vázquez MB, Witriw AM. *Modelos visuales de alimentos. Tablas de relación peso/volumen*, 1997, and López LB, Suárez MM. *Alimentación saludable. Guía práctica para su realización*, 2005 |
| Copy used | `density_FAO_INFOODS.xlsx`, in the team's Drive (dated 2026-10-08) | `Peso-Volumen-Medidas fmed.pdf`, in the same Drive folder |
| Checked against | The FAO PDF, as a spot check of the beverage rows | The PDF itself, page by page, since the text extraction mixes up its columns |

**Why FAO for density.** It is the one reference that covers the liquids and powders the catalog holds, and every value carries a code to its own bibliography (USDA, McCance and Widdowson, the Danish databank and others), so the origin of each number can be traced. It is also the source the issue proposed.

**Why the UBA table for unit weight.** It is in Spanish, uses Argentine products and sizes, and states that its values are net raw weight, which matches the edible portion SARA 2 uses (ADR-0025).

**USDA FoodData Central (`food_portion`)** was not used. It stays available as a fallback for the foods listed under "Foods without an equivalence".

### Licence of the FAO database

The PDF carries this notice: *"All rights reserved. FAO encourages reproduction and dissemination of material in this information product. Non-commercial uses will be authorized free of charge, upon request. Reproduction for resale or other commercial purposes, including educational purposes, may incur fees."* Requests go to copyright@fao.org. It is not an open licence: non-commercial use is authorized **on request**. That request has not been made yet, and it is a precondition for using the values outside the project's non-commercial setting.

### Criteria

1. **Specific gravity is read as density.** FAO states that both are the same when the reference water is at 4 °C. Entries that carry only specific gravity (UK 6th, spirits) are used as density.
2. **A range takes its midpoint** (`0.56-0.72` gives `0.64`).
3. **Priority between sources**: USDA, then UK 6th (McCance and Widdowson), then DK (Danish databank), then FNDDS 4.1, then the others. ASI (an industrial materials catalogue) and KEN (unpublished measurements taken at 1,350 m of altitude) are the weakest. When several entries match a food, the one named closest to it is used and the others are written in `notes`.
4. **`direct`** means the entry describes that food, including a generic entry that explicitly covers it and a fortified version of a milk (fortification does not change the kind of milk). **`family`** means the entry is a similar food or a generic category, and the `notes` column says which.
5. **Unit weight is the weight of the edible portion**, as ADR-0025 requires. The fruit and vegetable tables of the UBA document are gross weight (`P. Bruto`, with peel and stone) and were left out.
6. **Only the `g/unidad` column of the UBA table is used.** Its spoon-measure columns (`g/15 ml`, `g/10 ml`, `g/5 ml`, `g/100 ml`) are not, since densities already come from FAO.
7. **A unit weight is loaded only where a receipt's `unidad` is that unit.** The table gives the weight of one piece for biscuits, sweets, burgers and nuggets, and a receipt prints those by the package. Loading the weight of one biscuit would turn a packet of biscuits into 8 g.
8. **Boiled eggs reuse the raw weights** (50, 15 and 35 g) as `family`, because the table gives only raw ones.
9. **No food gets more than one value per kind**, and none gets a guessed one: a food that no source describes stays without a row.
10. **When the table gives several sizes of one product, the team picks the one loaded**: Danonino firme grande (80 g, the small one weighs 45) for the postre tipo Danonino, and Danonino bebible chico (90 g, the large one weighs 190) for the postre de leche bebible infantil.

### Values accepted after review

| Food | Value | Why it was reviewed |
| --- | --- | --- |
| Leche de cabra, entera, fluida | 1.08 | FNDDS value, high for a milk |
| Aceite de girasol | 0.96 | The rest of the oils sit at 0.92. Aceite de girasol alto oleico takes the same value as `family` |
| Crema de leche | 0.984 | FAO's closest entry is 38 % fat and SARA has 36.1 % |

Bebida a base de soja, sabor natural (1.08, FNDDS) has the same value as the goat milk and has not been reviewed.

### The seed

`seed_food_equivalences` in `seed_food_catalog.py` reads `app/reference_data/food_equivalences.csv` after the foods are seeded, and upserts each row by `(food_id, kind)`. The CSV is keyed by food code, as `food_nutrient_values.csv` is, and the seed resolves it to `foods.id`.

| Column | Loaded into | Content |
| --- | --- | --- |
| `food_code` | `food_id` | The catalog food |
| `kind` | `kind` | `density_g_ml` or `unit_weight_g` |
| `value` | `value` | The factor |
| `source` | `source` | The database, with the original reference of FAO's entry in brackets, for example `FAO/INFOODS Density DB v2.0 (UK 6th)` |
| `source_ref` | `source_ref` | The food's name in the source |
| `match_type` | `match_type` | `direct` or `family` |
| `notes` | nothing | The Spanish name of the entry, the other values the source has and the doubts, for whoever reviews the CSV |

An unknown `food_code` fails the seed, so a typo breaks the deploy and does not drop the row silently. The seed runs with the rest of the catalog from `scripts/pre_deploy.sh`.

## Coverage

171 rows: 139 densities (86 `direct`, 53 `family`) and 32 unit weights (25 `direct`, 7 `family`).

| Base unit | Foods | With an equivalence | Without |
| --- | --- | --- | --- |
| `litros` | 94 | 67 | 27 |
| `unidades` | 37 | 6 | 31 |
| `kilogramos` | 767 | 91 | 676 |

A food stocked in `kilogramos` needs no factor, except when a receipt prints it in `ml` or per unit, so the 676 without one are not a gap in the nutrition service.

Converting a food stocked in `litros` to grams needs its density, so 64 of the 94 convert. Three of the 67 with a row have only a unit weight: Leche fórmula inicio, Leche fórmula seguimiento and Postre de leche bebible infantil.

## Foods without an equivalence

### Stocked in `litros` with no density (30)

| Reason | Foods |
| --- | --- |
| FAO has no infant formula, and the one nearby entry is a different product (inicio and seguimiento have a unit weight from the UBA table) | Leche fórmula etapa 3, etapa 4, inicio, seguimiento, para prematuros etapa 1 y etapa 2 (all fluida); Leche seguimiento etapa 3, sabor vainilla |
| No entry that describes them (the postre has a unit weight from the UBA table) | Postre de leche bebible infantil; Alimento a base de almendras (leche de almendras); Aceto balsámico; Vinagre; Jugo de limón, envasado |
| FAO has flavoured water only without sugar, and no bitters | Agua saborizada Aquarius, Awafrut, Levité, tipo Manaos / Sierra de los Padres, "con azúcar, PROMEDIO"; Amargo serrano; Amargo serrano light |
| Their only close entry is the soy drink, whose value is in doubt, or the juice is of an unknown kind | Bebida a base de soja y jugo (sabores varios, y light); Jugo congelado con azúcar en sachet |
| Alcoholic drinks with no entry that fits, or with variants that differ and a food that does not say which (vermouth: 1.005 dry, 1.046 sweet) | Sidra; Vermouth; Aperitivo, tipo Gancia; Vino Mistela; Chicha; Cerveza sin alcohol |
| Soft drinks with 4 % of alcohol, which no entry describes | Ananá Fizz; Dr. Lemon |

### Stocked in `unidades` (31)

- Huevo de codorniz, entero, crudo y hervido, and Huevo de chocolate tipo Kinder: no source gives their weight.
- The 28 products of McDonald's: no source gives their weight. Whether they belong to Nutrir's stock is still open.

### Stocked in `kilogramos` and not loaded

- **FAO has contradictory values**: Harina de maíz (0.55 to 0.82), Harina de soja (0.64 and 0.70), Almidón de maíz (0.54 loose, 0.63 packed), leche en polvo (0.21 and 0.56), porotos, zanahoria (chopped and grated), ají y morrón (cubes and rings), copos de maíz, puré de papa instantáneo, aceituna verde (FAO weighs it with the stone, SARA without).
- **The UBA table gives several sizes, or several products that SARA names as one**: alfajores, galletitas de agua, grisines, pan francés, quesos, masa de tarta, dulce de membrillo y de batata, chorizo, probióticos (Activia 120 g, Actimel 100 g), yogur entero saborizado (pote chico 125 g, pote 200 g).
- **The UBA table gives the weight of a piece** (criterion 7): galletitas dulces, caramelos, hamburguesas industrializadas, nuggets.
- **Meats and fish**: the only FAO entries are bulk measurements of pieces with bone and are of no use to convert a volume.

## Consequences

- Nutrir and the recipes convert 64 of the 94 foods stocked in `litros` and 6 of the 37 stocked in `unidades`. The rest are left out with a warning that names the factor they lack.
- Every row says where its value comes from and how close the match is, and a reviewer can read the Spanish name of each FAO entry in `notes`.
- A `family` value is an approximation of a similar food. A milk-based drink with sugar or a formula would weigh somewhat more than the value taken from common milk.
- The seed only creates and updates. A row removed from the CSV stays in the table until it is deleted by hand or by a migration, and in this table a stale value keeps converting without anyone noticing.
- Many FAO values for powders and cut vegetables are bulk densities, and depend on how the food was packed or cut when it was measured.
- Using the values beyond non-commercial purposes requires FAO's authorization (see "Licence of the FAO database").

## Alternatives considered

- **Load the UBA fruit and vegetable weights with a waste factor.** Rejected: SARA 2 has no waste factors, and applying one from elsewhere would add a second unsourced number.
- **Load the gross weights as they are.** Rejected: they would overstate every nutrient computed from them, with nothing to flag the error (ADR-0025).
- **Fill the remaining gaps with a default** (1 g/ml, an average unit weight). Rejected for the same reason as in ADR-0025.
- **Delete from the table the rows that the CSV no longer has.** Not chosen: the other catalog seeds do not delete either, and it needs a decision of its own.
