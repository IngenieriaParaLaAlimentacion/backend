# ADR-0025: Unit conversion module and per-food equivalences

- **Status**: Accepted
- **Date**: 2026-10-23
- **Deciders**: Backend team
- **Related**: Issue #192 (unit conversion module), ADR-0012, ADR-0017, ADR-0021, ADR-0024, ADR-0027

## Context

Quantities of food live in three different units that cannot be compared directly:

- **Nutrient values** are per 100 g, exactly as SARA 2 states them (ADR-0012).
- **Stock and intake lines** are kept in each food's `base_unit` (`kilogramos`, `litros` or `unidades`), with no unit column of their own.
- **Receipts** print `g`, `kg`, `ml`, `cl`, `l` or `unidad`, whatever the shop chose.

The nutrition service works in grams (ADR-0021) and receipt prefill only accepts a quantity already printed in the food's base unit (ADR-0017). Both were waiting on a conversion that ADR-0012 deliberately left out: its rejected alternative, a per-food conversion table, was deferred "to whichever future feature actually needs it". Both features now need it.

## Decision

### One pure conversion module

`app/domain/unit_conversion.py` holds every conversion, with no database access. A food's equivalences are passed in as `ConversionFactors` (`density_g_ml`, `unit_weight_g`, each optional). Three operations:

| Operation | From | To | Used by |
| --- | --- | --- | --- |
| `to_grams` | base unit | grams | nutrition, recipes |
| `from_grams` | grams | base unit | `printed_to_base_unit`, recipes |
| `printed_to_base_unit` | printed unit | base unit | `prefill_from_printed` |

Each returns `Converted(value)` or `Unconverted(reason)`. A missing factor is never replaced by a guess: the reasons are `missing_density`, `missing_unit_weight` and `unsupported_unit` (printed unit not recognised).

`prefill_from_printed` applies the receipt's own rules on top of `printed_to_base_unit`: it returns the quantity to prefill on a receipt line, or nothing when the printed quantity is missing, cannot be converted, or converts to a value a line cannot hold (zero, or above `MAX_LINE_QUANTITY`).

### Units as a dimension and a size

Every unit is described by what it measures and how many of that dimension's smallest unit it holds:

| Unit | Dimension | Size |
| --- | --- | --- |
| `g` | mass | 1 g |
| `kg`, `kilogramos` | mass | 1000 g |
| `ml` | volume | 1 ml |
| `cl` | volume | 10 ml |
| `l`, `litros` | volume | 1000 ml |
| `unidad`, `unidades` | count | 1 unit |

The grams one of a unit weighs follow from its dimension alone:

```
mass    grams = size
volume  grams = size × density_g_ml
count   grams = size × unit_weight_g
```

`to_grams` multiplies by that figure and `from_grams` divides by it.

### Same dimension converts without factors

A printed unit of the same dimension as the base unit converts by the ratio of their sizes (`g → kg`,
`ml`/`cl → l`, `unidad → unidades`) and needs no factor. Going through grams would multiply and then divide by the same density, so a food with no density loaded would fail a conversion that does not depend on it.

A printed unit of another dimension goes through grams and needs the factors both units call for: `600 g` of a food stocked in `unidades` needs its unit weight; `3 unidad` of a food stocked in `kilogramos` needs it too.

### Decimal and rounding

All arithmetic is `Decimal`. `to_grams` and `from_grams` do not round, so a round trip `base → grams → base` returns the original quantity, and each caller applies the rule its quantity needs.

Receipt prefill (`printed_to_base_unit`) rounds half-to-even to the precision of the base unit:

- `kilogramos` and `litros` to three decimals, the scale of `Numeric(10, 3)` in `food_stock` and
  `food_intake_items`.
- `unidades` to a whole number.

Half-to-even keeps tie roundings from drifting a stock balance, which is a sum of many lines, upwards.

Recipes round their quantities down to three decimals instead, so a proposal never uses more than the stock holds (ADR-0024).

### Who converts

- **Nutrition** converts stock and monthly intakes to grams through `GramsConverter`
  (`app/services/nutrition/grams.py`), which reads the factors of all the foods in one query and returns a
  result per food. The nutrition service works in `float` from there on, and leaves out each food that did not
  convert with a warning naming it and the factor it lacks.
- **Recipes** convert the establishment's stock to grams for the solver, and the solver's grams back to stock
  units, through the same `GramsConverter`, loaded once per request. A food that does not convert is excluded
  with a warning (ADR-0024).
- **Receipts** prefill each matched line with `prefill_from_printed`, reading the factors of every matched food
  of a proposal in one query (ADR-0017).
- **Stock** converts nothing. Confirming a receipt, like any intake, takes quantities already in the food's base
  unit, so the stock is always kept in it.

### Equivalence table

One row per food and kind of factor:

| Column | Meaning |
| --- | --- |
| `food_id` | The catalog food, an FK to `foods.id` |
| `kind` | `density_g_ml` or `unit_weight_g` |
| `value` | The factor, `> 0` |
| `source` | Where the value comes from |
| `source_ref` | The food's name in that source |
| `match_type` | `direct` (that food) or `family` (taken from a similar food) |

Unique per food and `kind`. No row means no equivalence: there is no default density or weight.

The table is `food_equivalences`, plural like `foods`. It references `foods.id` rather than the food code the
issue names, because ADR-0012 makes `id` the only stable FK target. The seed CSV is keyed by food code, as
`food_nutrient_values.csv` is.

A unit weight is the weight of the **edible portion** of one unit, since SARA 2 gives nutrients per 100 g of
edible portion (ADR-0012): an egg is weighed without its shell. A weight with shell, bone or packaging would
overstate every nutrient computed from it, with nothing to flag the error.

The repository reads the factors of many foods in one query and returns them as `ConversionFactors` per food.
The real values are loaded by a seed from a CSV (ADR-0027); tests use made-up factors. No endpoint writes the table.

## Consequences

- `g` and `kg` convert with an empty table. Foods stocked in `litros` or `unidades` convert to grams only once their factor is loaded; until then the nutrition service leaves them out and reports why, per food.
- Receipts and the nutrition service share the module, so no conversion arithmetic lives anywhere else.
  `_STORED_UNIT`, which matched a printed unit to an identical base unit, was superseded by
  `printed_to_base_unit` and removed.
- A small quantity can round to zero (`20 g` of a food weighing 50 g per unit gives `0` units), while intake lines
  require a positive quantity. Receipt prefill leaves such a line empty, as it does one that cannot be converted.
- Only receipt prefill results are whole for `unidades`. Manual intakes and outflows still accept fractional units,
  and recipes keep three decimals.
- The `foods.grams_per_base_unit` column and `PUT /food-catalog/foods/{food_id}/gram-conversion`, a temporary
  adapter of the recipe recommendations, are removed. Their values were not transferred, and recipes now read
  `food_equivalences` like the other two features.
- A new base unit or printed unit needs its dimension and size in the module's tables before it converts. Tests run
  every member of `MeasurementUnit` and `PrintedUnit` through the conversions, so a missing entry fails them.

## Alternatives considered

- **Always convert through grams**, as a literal reading of the issue (`ml`, `cl` and `l` multiplied by the
  density). Rejected: within one dimension the density cancels out, and requiring it blocks `500 ml → 0.5 l` for a
  food with no density loaded.
- **Keep stock and intakes in grams** and convert only for display. Rejected: it migrates every stored quantity, and
  registering `12` eggs or `10 l` of milk by hand would require their factor before the intake could be saved at all.
- **A factor column on `foods`**, as the recipe recommendations first did with `grams_per_base_unit`. Rejected: a
  food may need both factors (a `kilogramos` food printed in `unidad`, a `litros` food printed in `g`), and each
  factor carries its own source and match type. One column also holds only the factor of the food's own base unit.
- **Default factors** (1 g/ml, an average unit weight). Rejected: they invent a value the source does not give.
- **`float` arithmetic.** Rejected: a round trip through a density is not exact.
- **Half-up rounding.** Not chosen: ties always round the same way, which biases a sum of many lines upwards.
