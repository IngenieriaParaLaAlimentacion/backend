# ADR-0020: Reference data and GAPA food classification behind the nutrition calculation

- **Status**: Accepted
- **Date**: 2026-10-10
- **Deciders**: Backend team
- **Related**: Issue #169 (nutrition calculation service), ADR-0010, ADR-0011, ADR-0012

## Context

The nutrition calculation judges a food combination against what a child of 7 to 9 years needs and against the
Argentine food guidelines (GAPA). That needs two kinds of data the catalog did not have:

- **What a child needs**: daily energy, the daily need of seven prioritized micronutrients, the share of the
  energy each macronutrient should provide, and limits for fiber, sodium, saturated fat and added sugar.
- **Which GAPA group each food belongs to.** The catalog classifies foods with SARA 2 categories, which do not
  match GAPA: `carnes` holds cold cuts that GAPA places in the optional group, and the cereals category mixes
  legumes, bread and pasta with cookies and pastries.

Some of these values are published and some are the criterion of a nutritionist consulted by the team. A reader
of the code must be able to tell which is which.

## Decision

### Reference values live in code, per profile

`app/reference_data/nutrition_references.py` holds one `ReferenceProfile` per kind of eater (`nino_7_9` today),
as frozen dataclasses versioned in git, like `who_bmi_for_age.py`. The need per 1,000 kcal is derived from the
daily need and the energy, never hard-coded. Another age is a new profile; the service interface does not change.

### GAPA group is a catalog attribute curated by hand

- Table `gapa_food_categories` (six rows) and a nullable `foods.gapa_category_id` (`ON DELETE RESTRICT`).
  `NULL` means "no group"; only the six salts, with no energy, have none. Every food with energy has a group
  (a test enforces it).
- The assignment is the `gapa_category` column of `foods.csv`, applied by the idempotent seed (ADR-0011). It
  started from a default per SARA category plus exceptions, and is edited by hand from then on; it is not
  regenerated from the data pipeline.
- No category-to-group rule runs at request time.

### Sources and criteria

| Datum | Value | Source |
| --- | --- | --- |
| Micronutrient needs, 7 to 9 years | calcium 700 mg, vitamin A 500 µg RE, folate 300 µg DFE, B12 1.8 µg, vitamin C 35 mg, iron 9 mg at 10% bioavailability, zinc 5.6 mg at moderate bioavailability | FAO/WHO (2001), *Human Vitamin and Mineral Requirements* |
| Energy | 1,770 kcal/day | FAO/WHO/UNU (2004), *Human Energy Requirements*: mean of the six values for ages 7-8, 8-9 and 9-10, boys and girls |
| Protein 10-15%, fat 15-30%, carbohydrates 55-75% of the energy | as stated | WHO/FAO (2003), TRS 916, Table 6 |
| Fiber at least 14 g per 1,000 kcal | as stated | **Criterion of a consulted nutritionist**, not checked against a published source |
| Saturated fat at most 10% of the energy, sugar at most 10% of the energy, sodium at most 2 g a day (about 1,130 mg per 1,000 kcal) | as stated | WHO/FAO (2003), TRS 916, Table 6. The table speaks of free sugars while the catalog only has added sugar |
| Risk of inadequacy | uncapped adequacy below 2/3 | Traditional fixed cutoff, National Research Council (1986), *Nutrient Adequacy: Assessment Using Food Consumption Surveys* |
| Composite indicator | mean of the seven adequacy ratios, each capped at 1 | INDDEX Data4Diets, mean adequacy ratio |

Exact URLs are in the module docstrings and next to the constants that use them.

### Calculation rules that follow from the data

- Vitamin A is counted in retinol equivalents, `RE = 2 × RAE − retinol`, per food before adding. A food with RAE
  but no retinol counts retinol as zero and says so in the warnings; it never invents a value.
- Fiber, sodium, saturated fat and added sugar are indicators only. The optimizer does not constrain them.
- Quantities are grams. Converting a food's `base_unit` to grams belongs to #155 and enters through the
  `GramsConverter` interface, so the calculation does not change when it lands.

## Consequences

- A change to a reference value or a food's group is a one-line edit reviewed in a PR, with no migration.
- Reference values cannot be edited at runtime. If someone needs that, they move to a table behind the same
  interface.
- One value rests on a nutritionist's criterion and not on a publication: the fiber floor.
  It is labeled as such and has to be validated with the project's nutritionists.
- The 2/3 cutoff marks a risk; it does not estimate how many people are inadequate. Current practice uses the
  estimated average requirement with a probabilistic method. Moving to it means adding that reference per
  nutrient.
- The per-food GAPA assignment is provisional: the mixed categories (cereals, meat, dairy) still need a
  food-by-food review, and the six group names were not checked against the application manual.
- Iron and zinc needs assume a bioavailability level and the catalog carries total content, so the result does
  not account for the actual diet or for fortification.

## Alternatives considered

- **Derive the GAPA group from the SARA category at request time.** Rejected: the categories mix groups, so
  every exception would become code.
- **An enum column on `foods`.** Rejected: a table gives the group a name, matches `food_categories`, and keeps
  the seed pattern of ADR-0011.
- **Reference values in a table.** Rejected for now: nobody edits them at runtime, and code in git gives review
  and history for free.
- **The estimated average requirement with a probabilistic method for the risk of inadequacy.** Not adopted:
  it needs reference values per nutrient that the project does not have yet.
