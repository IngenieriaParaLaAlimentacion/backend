# ADR-0022: Establishment characterization profile

- **Status**: Accepted
- **Date**: 2026-10-18
- **Deciders**: Backend team
- **Related**: ADR-0006 (establishment creation requests), ADR-0007 (establishment request review
  flow), ADR-0018 (field worker access to their own establishment's reads)

## Context

Recipe suggestions need to know what kind of place an establishment is: who attends, which meals it
serves, how it receives food and what kitchen it has. The profile was modeled on the Mapa Nacional
de Espacios Comunitarios de Cuidados form, plus the kitchen fields recipes need. The backoffice
already reads and writes it against a fixed contract:

- every field is optional, and the profile is replaced as a whole;
- `characterization_status` (`pending` / `complete`) is shown wherever an establishment is listed;
- the answer options are expected to change after review with nutritionists and community
  referents;
- a 422 must name the field that failed, so the form can flag the input without clearing it.

## Decision

### One `JSONB` column per table, validated by a Pydantic model

`establishments.characterization` and `establishment_requests.characterization` are nullable
`JSONB` columns. The profile is always read and replaced whole, and nothing queries inside it yet,
so a document column avoids about thirty columns or a 1:1 table with array columns, and an option
change needs no migration. `EstablishmentCharacterization`
(`app/schemas/establishments/establishment_characterization_schema.py`) is the only way in: values
outside the options, repeated, or out of range, and a `*_other` text without `"other"` chosen are
rejected before anything is stored.

A profile with no answered field is stored as `NULL`, so "never filled in" and "cleared" look the
same.

### Options live in one module

Every catalog is a `StrEnum` in `app/domain/establishment_characterization.py`. Adjusting an option
is a one-line change there, and the OpenAPI document picks it up. The cultural identity catalog is
provisional until referents validate it.

### The status is computed, never stored

`characterization_status()` in the same module returns `complete` when any value is not `null`,
`""` or `[]`. Both `Establishment` and `EstablishmentDomain` expose it as a property, so every
response built from either one (listing, detail, user and admin views, approval) carries it without
each caller computing it. Rows that existed before the column read as `pending` with no backfill.

### Editing is narrower than reading

`PUT /establishments/{id}/characterization` uses `check_characterization_edit_access`
(`app/services/access.py`): admins and superadmins edit any establishment, field workers only those
they have approved access to, and analysts none. `check_establishment_access` could not be reused
because it lets analysts through, which is right for reads (ADR-0018) but not for this write.

The full profile, which includes a private contact phone, is returned only by `PUT
/characterization`, `GET /dashboard` and the request endpoints, never by the public listing or the
map.

### Requests and approval

A creation request may propose a profile. On approval, the admin's final profile wins, and the
request's profile is used when the admin sends none. A reused establishment (same `place_id`) takes
the profile only if its own holds no answer, so an approval never overwrites data already curated
on that establishment.

### A 422 can name the failed field, on routes that opt in

The 422 envelope still does not name fields by default. A route sets
`openapi_extra={"x-invalid-field-extension": True}` to add a `field` extension. Its value is the
dotted body path of the first error, down to the first list index (`premises_other`,
`characterization.premises_other`, `opening_hours`). Only the name is returned, never the submitted
value, so a rejected secret is not echoed back.

## Consequences

- Option changes are cheap, but a renamed or removed value leaves old rows holding it: reading such
  a row back through the model fails. Renames need a data migration that rewrites the stored
  documents.
- Querying inside the profile (for example, establishments serving dinner) needs `JSONB` operators
  or a GIN index when it comes up.
- Opening hours are local `HH:MM` strings with no slot crossing midnight. Supporting overnight
  slots would relax the `closes_at > opens_at` rule.
