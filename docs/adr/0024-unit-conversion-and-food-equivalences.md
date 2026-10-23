# ADR-0024: Unit conversion module and per-food equivalences

- **Status**: Proposed
- **Date**: 2026-10-23
- **Deciders**: Backend team
- **Related**: Issue #192 (unit conversion module), ADR-0012, ADR-0017, ADR-0021

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
| `to_grams` | base unit | grams | nutrition |
| `from_grams` | grams | base unit | receipts, future recipe output |
| `printed_to_base_unit` | printed unit | base unit | receipts |

Each returns `Converted(value)` or `Unconverted(reason)`. A missing factor is never replaced by a guess: the reasons are `missing_density`, `missing_unit_weight` and `unsupported_unit` (printed unit not recognised).

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

All arithmetic is `Decimal`. Grams are not rounded, so a round trip `base → grams → base` returns the original quantity. Results in a base unit are rounded half-to-even:

- `kilogramos` and `litros` to three decimals, the scale of `Numeric(10, 3)` in `food_stock` and
  `food_intake_items`.
- `unidades` to a whole number.

Half-to-even keeps tie roundings from drifting a stock balance, which is a sum of many lines, upwards.

### Equivalence table

One row per food and kind of factor:

| Column | Meaning |
| --- | --- |
| food reference | The catalog food (see pending decisions) |
| `kind` | `density_g_ml` or `unit_weight_g` |
| `value` | The factor, `> 0` |
| `source` | Where the value comes from |
| `source_ref` | The food's name in that source |
| `match_type` | `direct` (that food) or `family` (taken from a similar food) |

Unique per food and `kind`. No row means no equivalence: there is no default density or weight. The repository reads the factors of many foods in one query and returns them as `ConversionFactors` per food. Loading the real values is a separate task; tests use made-up factors.

Pending decisions:

- **Table name.** `food_equivalences` is proposed, plural like `foods`.
- **Food reference.** The issue names `food_code`. ADR-0012 makes `foods.id`, not `code`, the only stable FK target, so a `food_id` FK to `foods.id` is proposed, with the seed CSV keyed by food code as `food_nutrient_values.csv` is.

## Consequences

- `g` and `kg` convert with an empty table. Foods stocked in `litros` or `unidades` convert to grams only once their factor is loaded; until then the nutrition service leaves them out and reports why, per food.
- Stock, receipts and the nutrition service share the module, so no conversion arithmetic lives anywhere else.
  `_STORED_UNIT` in `app/domain/printed_unit.py`, which matched a printed unit to an identical base unit, is
  superseded by `printed_to_base_unit` and goes away when receipt prefill moves to it.
- A small quantity can round to zero (`20 g` of a food weighing 50 g per unit gives `0` units), while intake lines
  require a positive quantity. Whoever stores the result decides what to do with a zero.
- Only conversion results are whole for `unidades`. Manual intakes and outflows still accept fractional units.
- A new base unit or printed unit needs its dimension and size in the module's tables before it converts. Tests run
  every member of `MeasurementUnit` and `PrintedUnit` through the conversions, so a missing entry fails them.

## Alternatives considered

- **Always convert through grams**, as a literal reading of the issue (`ml`, `cl` and `l` multiplied by the
  density). Rejected: within one dimension the density cancels out, and requiring it blocks `500 ml → 0.5 l` for a
  food with no density loaded.
- **Keep stock and intakes in grams** and convert only for display. Rejected: it migrates every stored quantity, and
  registering `12` eggs or `10 l` of milk by hand would require their factor before the intake could be saved at all.
- **Factor columns on `foods`** (`grams_per_base_unit`). Rejected: a food may need both factors (a `kilogramos`
  food printed in `unidad`, a `litros` food printed in `g`), and each factor carries its own source and match type.
- **Default factors** (1 g/ml, an average unit weight). Rejected: they invent a value the source does not give.
- **`float` arithmetic.** Rejected: a round trip through a density is not exact.
- **Half-up rounding.** Not chosen: ties always round the same way, which biases a sum of many lines upwards.
