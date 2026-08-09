# ADR-0006: Establishment creation requests live in their own dedicated table

- **Status**: Accepted
- **Date**: 2026-08-09
- **Deciders**: Backend team
- **Related**: `docs/api.md`, `app/models/establishment.py`

## Context

A field worker whose establishment is missing from the catalog can request its
creation (`POST /api/v1/establishments/requests`) so an admin can review it, fill
in the gaps, and register it — without the field worker leaving the access-request
flow. The request is a **notification** (reviewed by an admin),

The request payload differs structurally from an `Establishment` row in two ways:

- **All fields are optional** — the field worker may know nothing at all
  (`name`, `formatted_address`, `city`, `province` are each nullable). An
  `Establishment` requires `name`, `formatted_address`, `latitude`, `longitude`,
  `place_id`, `city`, and `province` (all `nullable=False`).
- **It has no georeferencing data.** `place_id`/`latitude`/`longitude` come from
  the Google Places API at registration time; a field worker describing a missing
  comedor has none of it. Fabricating values just to satisfy
  `Establishment`'s NOT NULL columns — either empty strings or placeholders —
  would pollute the georeferenced catalog and its future mapping features.

The review workflow is a separate concern: a request tracks *who* asked for what,
and an admin later either creates the establishment or closes the request.

## Decision

**Persist these notifications in a dedicated `establishment_requests` table** with
`user_id` (the field worker who created it), nullable free-text columns
(`name`, `formatted_address`, `city`, `province`), a `status` column defaulting to
`pending`, and `created_at`/`updated_at`. Length limits match the existing
`establishments` fields (100 characters) so what the admin completes is
compatible with the target table.

## Consequences

**Positive**

- The public `establishments` catalog (including the field-worker
  `available=true` listing) never shows rows that are not real, georeferenced
  comedores — a request does not masquerade as an establishment.
- The admin review flow (`repositories`/`services` layer of the `establishments`
  module) can later read pending requests, complete their nullable fields, and
  create the `Establishment` without touching schema again.


**Negative**

- One more table to maintain, and no uniqueness constraint prevents two field
  workers from requesting the same comedor. This is accepted: duplicate requests
  are visible to the admin in one review query, and deduplicating them is
  deliberately left out of the data layer (no `place_id` exists to key on
  anyway).

## Alternatives considered

**Add a status/flag to the `establishments` table itself** — rejected. All of
`Establishment`'s columns are NOT NULL and georeferencing is mandatory; a
"pending establishment" row would require placeholder coordinates and a fabricated
`place_id`, and every existing listing endpoint would have to learn to filter it
out. Mixing notifications with the catalog invites bugs everywhere the table is
read.

**Reuse `user_establishments` with a nullable `establishment_id`** — rejected.
That table is a many-to-many access relation with a composite primary key; a null
`establishment_id` violates the key, and its semantics (has this user been
granted access?) are unrelated to "please create this place."

**Generic notification table reused across modules** — rejected as premature
abstraction: there is no other notification entity in the system, and a
single-purpose table keeps the admin review query (status + user_id + dates)
trivial.