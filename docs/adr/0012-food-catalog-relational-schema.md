# ADR-0012: Relational schema for the food catalog

- **Status**: Accepted
- **Date**: 2026-08-30
- **Deciders**: Backend team
- **Related**: ADR-0010 (SARA 2 as the food catalog source), ADR-0011 (idempotent seed/upsert mechanism)

## Context

ADR-0010 settled *where* the food catalog's content comes from (SARA 2, raw/as-purchased entries only)
and ADR-0011 settled *how* it reaches the database (an idempotent upsert seed script, matched by a stable
`code`, run after `alembic upgrade head`). Neither ADR defines the actual table structure. This ADR does.

The catalog has to satisfy two things at once:

1. **A read-only reference list for stock logging.** Establishments will select from this catalog when
   recording food received. Each entry needs a defined unit of measurement so quantities logged by different
   establishments are comparable, and a stable identifier a future `food_stock` table can hold a real
   foreign key to (out of scope for this ADR — this ADR only has to guarantee that FK target exists and
   is stable).
2. **A faithful representation of what SARA 2 actually contains**, since ADR-0010 chose SARA 2 specifically
   for its nutrient composition data, in anticipation of nutritional reasoning (deficits, recommendations)
   in later work. Populating the catalog's own tables is the only point where the SARA 2 PDF gets parsed;
   deferring nutrient capture to later work would mean re-parsing the same source PDF a second time for
   data that's already being read out of it during this seed pass.

### What SARA 2 actually gives us

SARA 2 organizes its content as roughly 26 food groups (following the GAPA — Guías Alimentarias para la
Población Argentina — grouping logic), each containing a list of specific foods. For each food, in raw/
as-purchased state (per ADR-0010's scope), SARA 2 states nutrient composition **per 100 g of edible
portion** — the PDF states this explicitly ("posee los nutrientes expresados en 100 g de porción
comestible"), and it's applied uniformly across every food group, not just some. The nutrient panel itself
is fixed and identical across food groups: the same ~20 macronutrient fields (protein, total lipids,
carbohydrates, fiber, energy value, individual fatty acids, etc.) and the same ~19 vitamin/mineral fields
(iron, calcium, vitamin C, zinc, etc.) are reported for every food, for a combined ~39 nutritional
components — consistent with the figure already cited in ADR-0010.

SARA 2 does **not** provide:

- Any concept of a purchasing or receiving unit (it has no notion of "this food is normally sold by the
  unit" vs. "by weight") — its only stated basis is the 100 g nutrient reference, which serves nutrient
  composition, not stock logging.
- Cut-level detail for meats (no IPCVA-style breakdown such as bife angosto, cuadril, etc.) — entries for
  meat are at the whole-species/preparation level (e.g. a single generic "Vacuno" entry, "Pollo con piel" /
  "Pollo sin piel"), with a smaller set of named organs and processed/cured products alongside them, not
  named per-species. There is therefore no reliable parent/subtype grouping available from the source for
  a type→subtype hierarchy beyond a small number of unambiguous cases.
- Perfectly clean, universally populated data: some individual `(food, nutrient)` readings are blank in
  the source PDF rather than zero (confirmed during extraction — several nutrient columns, including
  copper, ash content, magnesium, niacin, and iron readings, required a dedicated blank-cell verification
  pass to avoid misreading an absent PDF cell as a `0` value). A `0` and "not measured" are not the same
  claim, and the schema needs to preserve that distinction rather than silently coercing blanks to zero.

## Decision

Four tables. All use a UUID surrogate primary key (`id`), consistent with every other model in this
codebase, and standard `created_at`/`updated_at` timestamp columns.

### `food_categories`

The ~26 SARA 2 food groups.

| Column | Type | Rationale |
|---|---|---|
| `id` | UUID, PK | Surrogate key; the only thing any FK in this schema ever points at. |
| `code` | String, unique, not null | Stable natural key for the seed script's upsert matching, per ADR-0011 — matched by a slug derived from the group name, not by the display name itself, so a later wording correction doesn't create a duplicate group. |
| `name` | String, not null | Display name of the group (e.g. "Carnes"), as given by the source. |

This is modeled as a real table rather than a fixed enum for the same reason ADR-0011 rejected persisting
the catalog itself as in-memory constants: group names are part of the source and can be corrected as the
seed data is curated and reviewed (ADR-0011 already anticipates the catalog is not write-once). An
already-applied enum value is exactly as costly to correct as an already-applied migration — a table with
an upsertable row avoids that.

### `foods`

The specific, individual foods an establishment actually selects when logging stock.

| Column | Type | Rationale |
|---|---|---|
| `id` | UUID, PK | Surrogate key. This — not `code` — is what a future `food_stock`/`food_intake` entry references, so that renaming a food's `code` later (a risk ADR-0011 already flags) never breaks an existing reference; only the seed script's own upsert matching depends on `code`. |
| `code` | String, unique, not null | Stable natural key for upsert matching, per ADR-0011, derived from the food's name (e.g. `pollo_pechuga_sin_piel`). |
| `name` | String, not null | Display name, as given by the source (e.g. "Pechuga de pollo sin piel"). |
| `category_id` | UUID, FK → `food_categories.id`, `ON DELETE RESTRICT`, not null | Every food in SARA 2 belongs to exactly one of the 26 groups; `RESTRICT` prevents a category from being removed while foods still reference it. |
| `base_unit` | Enum, not null | The unit of measurement an establishment's logged quantity for this food is persisted in. This is a domain decision this catalog has to make on SARA 2's behalf, since the source has no purchasing/receiving unit concept at all — it only defines a 100 g nutrient reference basis, which answers a different question. The unit is chosen per food to match how it is realistically received (e.g. counted for eggs, weighed for meat), so that quantities logged for it are always recorded in a unit coherent with the food itself. |
| `source_page` | SmallInteger, nullable | The PDF page the entry was read from. Supports the same auditability requirement ADR-0010 raises for the source as a whole, at the level of an individual entry — a reviewer correcting a curated value can go straight to the page it came from. |

The table is named `foods`, not `food_types`: each row is the definitional catalog record itself, and no
other table in this codebase uses a `_type` suffix for a reference/catalog table (`establishments`,
`surveys`, `subjects` are all plain nouns) — this keeps the naming consistent with that pattern, including
downstream (`food_stock.food_id`, not `food_stock.food_type_id`).

### `nutrients`

A dictionary of the nutrient components SARA 2 measures — populated once, independent of any specific
food.

| Column | Type | Rationale |
|---|---|---|
| `id` | UUID, PK | Surrogate key; FK target for `food_nutrient_values`. |
| `code` | String, unique, not null | Stable natural key for upsert matching (e.g. `protein`, `iron`), same rationale as `foods.code`. |
| `name` | String, not null | Display name, as given by the source (e.g. "Proteínas", "Hierro"). |
| `unit` | String, not null | The unit this nutrient's own values are expressed in per the source (e.g. `g` for protein, `mg` for iron, `kcal` for energy value) — SARA 2 uses a different unit per nutrient, not one uniform unit across all 39. |
| `group` | Enum, not null | `macronutrient` / `vitamin` / `mineral` / `fatty_acid` — mirrors the source's own split of each food's composition into a macronutrient table and a separate vitamins-and-minerals table. |

Modeled as a table, not an enum, for the same reason as `food_categories`: with roughly 39 members, each
carrying its own unit and group rather than being a bare label, a table is both more practical to maintain
and consistent with how every other piece of curated, source-derived reference data in this catalog is
handled — as an upsertable row, not a value baked into a migration.

### `food_nutrient_values`

The actual measurements: one row per `(food, nutrient)` reading that SARA 2 reports.

| Column | Type | Rationale |
|---|---|---|
| `id` | UUID, PK | Surrogate key. |
| `food_id` | UUID, FK → `foods.id`, `ON DELETE CASCADE`, not null | Owned detail data of a food — if a food is removed, its nutrient readings have no independent meaning and are removed with it. |
| `nutrient_id` | UUID, FK → `nutrients.id`, `ON DELETE RESTRICT`, not null | Prevents a nutrient definition from being removed while values still reference it. |
| `amount_per_100g` | Numeric, not null | The value exactly as SARA 2 states it — per 100 g of edible portion, with no unit conversion or derivation applied, so that any stored value can be checked directly against the source page it came from. |
| — | `UNIQUE(food_id, nutrient_id)` | A food has at most one reading per nutrient. |

This is a normalized `(food, nutrient) → value` table rather than one column per nutrient on `foods`,
for two reasons grounded directly in the source data:

1. **Scale.** ~39 nutrient components per food, applied to a catalog of several hundred foods, would mean
   most of those ~39 columns sitting unused by any feature at a given time — the source reports the same
   fixed panel for every food regardless of which of its components a given feature actually consumes.
2. **Genuine sparsity at the value level.** SARA 2 does not report a value for every `(food, nutrient)`
   pair — some cells are blank in the source rather than zero, confirmed while extracting the source (see
   above). A normalized table represents "not measured" as the simple absence of a row; a fixed-column
   table would require a `NULL` in a specific column, and every future computation over that data would
   have to remember, forever, never to treat that `NULL` as `0`.

`foods.base_unit` and `food_nutrient_values.amount_per_100g` are intentionally not bridged by any column
in this schema (e.g. a weight-per-unit factor). SARA 2 provides no such conversion data for anything other
than weight-based units, and sourcing it (for foods counted or measured by volume) would require a
different, secondary source entirely. Since no functionality defined for this catalog computes a nutrient
total from a logged stock quantity, that bridge is left for whichever future feature actually needs it, to
be solved — and sourced — at that time, scoped to only the foods it actually requires.

## Consequences

*Positives*

- Every column in `foods` and `food_nutrient_values` is either a direct, unmodified reading from the
  source or a minimal domain addition (`base_unit`) required for stock logging — nothing is speculative or
  derived through an unaudited calculation.
- `food_nutrient_values` captures the full nutrient panel SARA 2 provides during the same seed pass that
  populates `foods`, so future nutrition-facing functionality (deficit calculations, recommendations — the
  motivating use case ADR-0010 names for choosing SARA 2 in the first place) does not require re-parsing
  the source PDF.
- Blank source cells are represented as absent rows, not as `0`, avoiding a false "this food has none of
  this nutrient" claim where the source simply didn't measure it.
- `foods.id`, not `code`, is the only stable FK target in the schema, so a future correction to a food's
  `code` cannot break any existing reference to it.

*Negatives*

- `foods.base_unit`'s enum membership was closed during Stage 2 curation: `unidades` / `kilogramos` /
  `litros`. A fourth candidate, `potes`, was dropped — it wasn't sourced from SARA 2 (which has no
  unit-of-purchase column at all) and added variety without a real distinction, since anything sold by
  weight — including packaged single-serve items — maps cleanly to `kilogramos`. Extending the enum
  later, if a real gap turns up, is a migration, consistent with existing precedent in this codebase (see
  `3c300b242b41_add_revoked_to_userestablishmentstatus_`, which added a new enum member to an existing
  status type).
- Computing a derived quantity (e.g. total protein delivered from a logged stock entry) requires future
  work to define and source a `base_unit`-to-grams conversion for any food not already measured by
  weight. This ADR deliberately does not solve that problem now.
- Nutrient values on foods logged by volume or count (`litros`, `unidades`) cannot be scaled to a
  received quantity without that same future conversion — this is a direct consequence of storing nutrient
  data exactly as the source states it (per 100 g) rather than pre-converting it to match each food's
  `base_unit`.

*Neutral*

- No type→subtype hierarchy is modeled. SARA 2 does not provide cut-level detail for meats beyond a small,
  largely unambiguous set of cases (e.g. `Pollo con piel` / `Pollo sin piel`), and nothing in the source
  supports a general parent/child grouping across the rest of the catalog. Should a concrete need for
  category-level aggregation emerge later (e.g. "total kg of meat received"), a nullable
  `parent_food_type_id` self-reference on `foods` can be added additively, without altering any existing
  column or row.

## Alternatives considered

**One column per macro/micronutrient on `foods`, instead of `nutrients` + `food_nutrient_values`** —
rejected. Workable only for a small, fixed subset of nutrients decided in advance; SARA 2 provides the
full ~39-component panel uniformly for every food regardless of which subset a given feature needs, and a
fixed-column table cannot express "not measured" distinctly from "measured as zero" without every future
query independently guarding against misreading a `NULL`.

**`foods.base_unit` as a single, fixed unit for every food (e.g. always `kilogramos`)** — rejected. SARA 2
defines no purchasing/receiving unit at all, so there is no source basis for a single universal choice; a
per-food unit is required regardless. A single fixed unit would also be operationally unrealistic for
foods that are naturally counted rather than weighed (e.g. eggs) — establishments log egg quantities as a
count (`unidades`), not a weight (`kilogramos`), so a single global unit cannot represent both correctly.

**A `food_unit_conversions` table plus a `grams_per_base_unit` bridging column, to let a logged quantity
be entered in an alternate unit and scaled to a nutrient total** — rejected for this schema. SARA 2
supplies no weight-per-unit or per-volume density data for anything other than already-weight-based
foods; sourcing it would require a secondary, external reference for every food measured by count or
volume, for a computation (deriving a nutrient total from a logged stock quantity) that no functionality
defined for this catalog performs. Deferred to whichever future feature actually needs it. Adopted later, as
a `food_equivalences` table, once the nutrition service and receipt prefill needed it (ADR-0024).

**`food_categories` as a fixed enum instead of a table** — rejected, for the same reason ADR-0011 rejected
enum/in-memory constants for the food catalog itself: group names are part of the curated, reviewable
source data, not a fixed structural detail of the application, and an enum value is exactly as costly to
correct later as an already-applied migration.

**A `sara2_group_number` column on `food_categories`, to trace each category back to SARA 2's own 1–26
group number** — rejected. Source traceability for the grouping itself is already
covered by ADR-0010 documenting SARA 2 as the source. A "1-of-26" group number is also not something this
schema could guarantee stays populated if a future non-SARA2 source ever contributes a category — unlike
`foods.source_page`, whose audit value is at the individual-food level SARA 2 doesn't otherwise expose.

**An `is_active` column on `foods`, to let a food be retired from the catalog — rejected for now. No catalog-correction 
workflow exists yet that needs to retire a food, so the column would carry no behavior beyond a query filter with 
nothing to filter. Nothing about a food being *removed from the catalog* is expected to happen during normal operation 
— a food isn't the kind of thing that becomes seasonally or temporarily unavailable, unlike, say, a paused survey. 
If a genuine catalog-correction need appears later (once real stock data exists to protect), this can be added
as an additive migration at that point, informed by whatever the actual correction workflow turns out to
require, rather than speculatively now.
