# ADR-0012: Relational schema for food intakes

- **Status**: Accepted
- **Date**: 2026-09-05
- **Deciders**: Backend team
- **Related**: ADR-0011 (relational schema for the food catalog), ADR-0004 (offline-first response sync via client ids)

## Context

ADR-0011 built the food catalog and explicitly stopped at the point where an establishment would
actually *use* it: it guarantees that `foods.id` is a stable FK target for "a future
`food_stock`/`food_intake` entry", but models nothing about what an establishment receives. This ADR
defines that entity.

The requirement is that an establishment can record a delivery — a batch of food that arrived on a
given date, loaded either by hand or from a photo — as one entity grouping one or more food lines,
each line pointing at a catalog food with a quantity. Registration, querying and enrichment of that
data are built on top of it in later work; this ADR only settles the schema.

Three constraints shape it:

1. **It has to behave like `measurements`.** That module already establishes this codebase's answer
   for "a field worker records something at an establishment": UUID PK generatable by the client,
   `RESTRICT` on the actor and establishment FKs, `CASCADE` on owned child rows, an event timestamp
   separate from the row's `created_at`, and a `synced_at` column for the offline sync path. There is
   no reason for food intakes to answer any of those questions differently.
2. **The unit is the catalog's to define, not the intake's.** ADR-0011 put `base_unit` on `foods`
   precisely so that quantities logged by different establishments are comparable.
3. **Enrichment is coming and must not force a re-model.** Supplier/donor, receipt number, estimated
   monetary value and a photo attachment are all anticipated but out of scope, and the schema must
   absorb them without a destructive migration.

## Decision

Two tables, UUID surrogate primary keys, consistent with every other model in this codebase.

### `food_intakes`

One delivery received by an establishment.

| Column | Type | Rationale |
|---|---|---|
| `id` | UUID, PK | Surrogate key, defaulted client-side (`uuid.uuid4`) so a mobile client can generate it offline and replay the same intake idempotently, exactly as `measurements` does per ADR-0004. |
| `establishment_id` | UUID, FK → `establishments.id`, `ON DELETE RESTRICT`, not null | Who received the food. `RESTRICT` matches `measurements.establishment_id`: an establishment with recorded history must not be silently removable. |
| `responsible_id` | UUID, FK → `users.id`, `ON DELETE RESTRICT`, not null | The user who loaded the intake. `RESTRICT` matches `measurements.responsible_id` — attribution of a record must survive. |
| `received_at` | DateTime(tz), not null | When the food actually arrived. Deliberately distinct from `created_at`, so a retroactive load (a delivery recorded days later, or synced from an offline device) keeps both facts. Same split as `measurements.measured_at` vs `created_at`. |
| `comments` | String, nullable | Free-text note about the delivery. Optional by definition — most intakes have nothing to say. |
| `source` | Enum (`foodintakesource`), not null | `manual` / `photo`: how the intake was loaded. Kept as a column rather than inferred from the presence of an attachment, because the attachment itself is not modeled yet and a photo-loaded intake is still a photo-loaded intake once its image is discarded. |
| `synced_at` | DateTime(tz), nullable | When the record reached the server from an offline client; null for a direct online load. Mirrors `measurements.synced_at`. |
| `created_at` | DateTime(tz), `server_default now()`, not null | Row creation. |
| `updated_at` | DateTime(tz), `server_default now()`, `onupdate now()`, not null | Last correction. |
| — | `INDEX(establishment_id, received_at)` | The access path every intake listing will use: one establishment's deliveries, most recent first. |

Intakes are correctable in place: a delivery's
recorded amount or date can turn out wrong, and `updated_at` says when that was last fixed.

### `food_intake_items`

One food line of an intake.

| Column | Type | Rationale |
|---|---|---|
| `id` | UUID, PK | Surrogate key. |
| `food_intake_id` | UUID, FK → `food_intakes.id`, `ON DELETE CASCADE`, not null | Owned detail data of an intake — a line has no meaning without the delivery it belongs to, and goes with it. Same relationship `measurement_alerts` has to `measurements`. |
| `food_id` | UUID, FK → `foods.id`, `ON DELETE RESTRICT`, not null | The catalog entry, referenced by `id` as ADR-0011 requires. `RESTRICT` is what makes ADR-0011's `is_active` flag the correct way to retire a food: a food referenced by a logged intake cannot be deleted, only deactivated. |
| `quantity` | Numeric(10, 3), not null | How much arrived, in the food's own `base_unit`. `Numeric`, not `Float` — a received quantity is exact data, and `Float` is used in this codebase only for anthropometric readings. Three decimals expresses grams within a `kilogramos` quantity. |
| `created_at` | DateTime(tz), `server_default now()`, not null | Row creation. |
| — | `CHECK (quantity > 0)` | A line recording zero or a negative delivery is meaningless; enforced in the database rather than only at the edge, since this table will be written by more than one path (manual load, photo load). |
| — | `INDEX(food_intake_id)`, `INDEX(food_id)` | Loading an intake's lines, and answering "where has this food been received". |

**There is no `unit` column on the line.** The unit of a quantity is the referenced food's
`base_unit`, read through the `food` relationship. ADR-0011 chose `base_unit` per food specifically so
that logged quantities are always in a unit coherent with the food itself; copying it onto the line
would create a second copy of the same fact that a later catalog correction could leave disagreeing
with the catalog, with no rule for which one wins.

**There is no `UNIQUE(food_intake_id, food_id)`.** Two lines of the same food in one delivery is
legitimate — two batches from two donors, or a quantity counted twice at intake — and collapsing them
is a decision for whoever registers the intake, not a constraint the schema should impose.

## Consequences

*Positives*

- An intake is enrichable additively (CA 3): `supplier_name`, `receipt_number`, `estimated_amount`
  and a photo reference are all nullable columns on `food_intakes` that can be added without touching
  an existing column, row or constraint. Nothing in this schema needs to be undone to accept them.
- `received_at` being independent of `created_at` means retroactive and offline-synced loads are
  representable from day one, with no backfill needed later.
- A quantity is never stored with a unit that can drift from the catalog's.
- Deleting an intake removes its lines and nothing else — the catalog, the establishment and the user
  are all protected by `RESTRICT`.

*Negatives*

- Because the unit is derived, correcting a food's `base_unit` in the catalog silently reinterprets
  every historical quantity logged against it. This is the accepted cost of not duplicating the fact;
  it is a catalog-curation concern, and ADR-0011 already treats `base_unit` as a curated, reviewed
  value rather than one expected to churn.
- Reading an intake's units requires loading the referenced foods (`selectinload`), so no listing can
  render a quantity's unit from the intake tables alone.
- Nutrient totals for an intake remain uncomputable, for exactly the reason ADR-0011 gives: no
  `base_unit`-to-grams bridge exists for foods measured by count or volume. This ADR does not solve
  that either.

*Neutral*

- The `foodintakesource` enum is closed at `manual` / `photo`. Adding a member later (e.g. a bulk
  import) is an `ALTER TYPE ... ADD VALUE` migration, the same precedent as
  `3c300b242b41_add_revoked_to_userestablishmentstatus_`.
- No stock/balance concept is modeled. This entity records what *arrived*; what is currently *held*
  (consumption, spoilage, running balance) is a separate question that a future feature can answer by
  aggregating over intakes plus its own outflow table, without changing anything here.

## Alternatives considered

**Snapshotting the unit onto `food_intake_items` at write time** — rejected. It buys immutability of
historical rows against a catalog edit, at the cost of a denormalized column that can disagree with
`foods.base_unit` with no rule for resolving the conflict. ADR-0011 already assigned the unit to the
food, and this preserves that single source of truth. Should immutable historical units ever become a
real requirement (e.g. an audited report), the column can be added and backfilled from the catalog
additively.

**A flat `food_intakes` table with one food and one quantity per row, no line table** — rejected. A
delivery is naturally several foods at once, and flattening it would either duplicate the date,
responsible, source and comments across every food, or lose the fact that they arrived together —
which is precisely the grouping a photo-loaded delivery produces.

**Adding the enrichment columns (`supplier_name`, `receipt_number`, `estimated_amount`,
`photo_url`) now** — rejected. Every one of them is additive and nullable, so adding them now buys
nothing that adding them later doesn't, while committing to shapes (is a supplier free text or an FK
to a donors table? is an attachment a URL or a storage key?) that the feature actually needing them is
better placed to decide.

**Storing `quantity` as `Float`, matching `measurements.weight_kg`** — rejected. Anthropometric
readings are measurements with inherent instrument error; a received quantity is a recorded fact that
will be summed across intakes for reporting, where accumulated binary-float error is not acceptable.
`Numeric` is what the catalog already uses for `amount_per_100g` for the same reason.
