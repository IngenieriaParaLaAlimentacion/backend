# ADR-000X: Food catalog population via an idempotent seed script (upsert), not Alembic data migrations

- **Status**: Accepted
- **Date**: 2026-08-28
- **Deciders**: Backend team
- **Related**: ADR-0009 (SARA 2 as the food catalog source)

## Context

The food type catalog needs a real, queryable table so that food intakes can reference each entry by a stable foreign key. 
This rules out the pattern already used elsewhere in the repo for reference data without persistence 
(`app/reference_data/`, e.g. `who_bmi_for_age.py`), which is plain Python constants read in memory and never written to 
the database — sufficient for lookup-only data, but incompatible with the requirement of a real FK from food intakes 
to catalog entries.

No migration in the repository's history contains an `INSERT`/`bulk_insert`/`execute` of data; every existing migration 
is pure DDL (tables, indexes, columns, enum backfills). The only existing pattern in the codebase that both persists 
data to a real table and runs automatically on every deploy is `seed_superadmin.py`: an idempotent Python script, run 
from the container's entrypoint right after `alembic upgrade head` and before starting the server, using the existing 
ORM/UnitOfWork pattern.

Additionally, the food catalog is not a write-once dataset: names will be corrected, new foods will be added, and 
categories may be adjusted over time as the seed sourced from SARA 2 is curated and reviewed. A mechanism that treats 
the catalog as something inserted once and then left alone would make every future correction as costly as a schema 
change, since an already-applied Alembic migration is not meant to be edited — fixing so much as a typo would require 
a brand-new migration each time.

## Decision

The food catalog is populated by an **idempotent seed script that performs an upsert**, following the same execution 
pattern already proven in production by `seed_superadmin.py`:

- The curated list of foods (derived from SARA 2, per ADR-0009) lives in a **plain data file** (JSON or CSV) checked 
into the repository — one entry per food, human-reviewable in a pull request diff.
- A **seed script** (e.g. `seed_food_types.py`), using the existing ORM/UnitOfWork pattern, reads that file and
**upserts** each entry into the `food_types` table, matched by a **stable natural key** (a code/slug, not the display 
name) so that renaming or correcting a food's name updates the existing row instead of creating a duplicate.
- The script runs automatically as part of the container's boot sequence, after `alembic upgrade head` and before the 
application server starts — the same point in the lifecycle where `seed_superadmin.py` already runs.
- Alembic migrations remain strictly DDL for this catalog: they create/alter the `food_types` table structure, but never 
carry `INSERT` statements for its rows.

## Consequences

*Positives*
- Reuses an execution mechanism that already exists, runs in production today, and is well understood by the team — 
no new deployment step or tool is introduced.
- Corrections and additions to the catalog are as simple as editing the data file and committing — no new migration needs 
to be authored for a typo fix or an added food.
- The data file itself is easy to review in a pull request: a one-line change shows as a one-line diff, unlike a 
migration file with an embedded `bulk_insert` call.
- Upserting by a stable code (rather than by name) avoids duplicate rows when a display name is corrected.

*Negatives*
- Requires defining and maintaining a stable code/slug per food item, an additional field that must be chosen carefully 
upfront (renaming a code later is a breaking change for any food intake already referencing it).
- The seed script must be written carefully to remain idempotent and side-effect-free on every boot (it runs on every
deploy, not just the first one), which is slightly more logic than a one-time insert.

*Neutral*
- This decision only concerns *how* catalog rows reach the database. It does not affect ADR-0009, which concerns 
*where* the catalog's content comes from — the two can evolve independently.

## Alternatives considered

**Alembic data migration (`INSERT` shipped inside a migration)** — rejected. There is no precedent for this in the 
codebase; every existing migration is pure DDL. Beyond the lack of precedent, it has a structural downside for a 
catalog that will keep changing: an already-applied migration is not meant to be edited, so every future correction
(a typo, a renamed food, a new entry) would require authoring a brand-new migration, mixing schema history with what is 
really just data maintenance.

**Plain Python constants in `app/reference_data/` (no persistence)** — rejected. This is the pattern already used for 
other reference data in the project (e.g. WHO growth tables), and it is the simplest option to version and edit. 
It was ruled out because it does not persist to the database at all, and the catalog requires a real foreign key from 
food intakes to a specific catalog entry — a requirement plain in-memory constants cannot satisfy.

**One-time seed insert without upsert logic** — rejected. Functionally similar to the chosen approach but without 
idempotent matching by a stable key, this would only handle the initial population correctly; any later correction would
either need to be done by hand directly in the database (breaking traceability) or would risk duplicating rows if the 
script were naively re-run.