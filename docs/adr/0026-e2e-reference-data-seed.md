# ADR-0026: E2E reference data as a guarded, repeatable seed script

- **Status**: Accepted
- **Date**: 2026-10-24
- **Deciders**: Backend team
- **Related**: Issue #210, ADR-0002 (FIES as a template), ADR-0008 (survey response target), ADR-0011
  (idempotent seed script for the food catalog), ADR-0014 (materialized food stock)

## Context

The E2E tests and the user manual's screenshots need the same starting state: users of every role,
establishments on the map, people with measurements, stock with movements and a FIES survey with
responses. Today only the superadmin and the food catalog are seeded, and both run in the
pre-deploy step (`scripts/pre_deploy.sh`), so in production too.

The state has to come from somewhere that is neither production nor a test's own fixtures: the
integration tests build their data per test and truncate every table between tests, and the E2E tests
create their own records through the API and expect a stable base underneath.

Two facts of the codebase shape the solution:

- The API almost never deletes. Only surveys without responses can be deleted; establishments, subjects,
  measurements, requests and stock movements cannot. The data cannot be cleaned, only rebuilt on a new
  database.
- Some data is derived. A measurement produces its alerts, and stock is kept in step with intakes and
  outflows (ADR-0014). A row inserted without the service that owns the rule leaves the others wrong.

## Decision

### A script that the startup and the deploy never run

`seed_reference_e2e.py` is a script like `seed_superadmin.py` and `seed_food_catalog.py`, not an
endpoint: it adds no door to the API and cannot be exposed in production by mistake. It is not in the
`CMD` of the image or in any deploy step. The E2E compose runs it, after the migrations and the
other two seeds, and a person can run it by hand.

### It only runs when `ENVIRONMENT` is `e2e`

The script exits unless `ENVIRONMENT` is `e2e`. Currently we host two different environments. The `ENVIRONMENT` envar can be `production` or `development` and this seed should not modify either of them.

### The data lives apart from the code that loads it

`app/reference_data/reference_e2e_dataset.py` holds the data as frozen dataclasses. It refers to
establishments by key, foods by catalog code and times as "N days ago". The script resolves them to ids
and dates when it runs. The API's request schemas need those resolved values, so they cannot hold the
dataset themselves.

Everything is made up. Establishments are named after public squares, so the addresses are real places
but no real organisation is attributed to them. National ids start at 90,000,000, above any real one.
Every user shares one password, which is documented in `docs/commands.md`.

### Services for what has rules, repositories for accounts and access

Establishments, subjects, measurements, intakes, outflows, surveys and responses go through their
services, so alerts and stock come out as in production. Users, their access to establishments and the
pending establishment requests go through repositories: the services only create them through the
registration and approval flows, which involve mail and tokens.

### Repeatable through fixed ids

Each record gets an id from `uuid5` over a fixed namespace and its key. The services already treat a
repeated id as a replay and change nothing, so most of the script has no "does it exist" logic. The rest
is looked up before it is created: users by email, establishments by place, the survey by name and
access by upsert. A run that stopped half way is finished by running it again.

### The FIES survey is anonymous, and each response has its own unit of work

A survey takes one response per subject or per establishment, so a survey about subjects would have
capped the 10 responses at the number of people. The FIES template already defaults to the anonymous
target (ADR-0008). Each response is submitted in its own unit of work, as a request would be: a response
updates the survey's counter, and a session shared by several of them reads the survey stale and fails
on a lazy load.

## How it is used

**On a developer's machine**, from an empty database and in this order, because the dataset moves
stock of catalog foods and stops naming the ones missing if they are not there:

```bash
docker compose up -d postgres
poetry run alembic upgrade head
poetry run python seed_food_catalog.py
ENVIRONMENT=test poetry run python seed_reference_e2e.py
poetry run uvicorn app.main:app --reload
```

The screenshots of the user manual are taken from this state, logged in as the users listed in
`docs/commands.md`. To start over, drop the database and repeat.

**In the E2E runs of the backoffice**, `e2e/compose.yml` runs it after the migrations and the other two
seeds, in a service of its own that the backend waits for. `e2e/.env.e2e` sets `ENVIRONMENT=e2e`, which
the script accepts. It is the base under the tests, not their data: what a test changes it creates itself.

**In a shared environment**, nothing runs it. It is in no deploy step, and whoever runs it there by
hand has to set `ENVIRONMENT` knowing that what it adds cannot be removed through the API.

## Consequences

- To start over, use a new database. Running the script again adds nothing and never changes what is
  there, which is not the same as restoring the starting point: a record that a test changed, such as a
  pending request it approved, stays changed. Tests that change these records need data of their own.
- Dates are relative to the day of the first run, and the ages to the day each person is created. A
  later run does not move them. Nobody in the set is older than 25 on that day.
- The script depends on the services' contracts, so a change to a request schema or a rule can break
  it. The integration test runs it twice and logs in as every user, so the CI shows it.
- Anyone who runs it locally has to set `ENVIRONMENT=test` for that command. That friction is the
  barrier.

## Alternatives considered

- **An endpoint.** Rejected: it adds a door to the API that production would also have.
- **Inserting every row with the ORM or SQL.** Rejected: alerts and stock would not match the rules, and
  every schema change would break it silently.
- **A SQL dump or static fixtures.** Rejected for the same reasons, and they do not repeat.
- **The integration tests' fixtures.** Rejected: they are built per test and truncated after it.
- **An Alembic data migration.** Rejected, as in ADR-0011: it would run on every deploy, production
  included.
- **A guard against production only.** Rejected: it fails open when `ENVIRONMENT` is not set.
- **A survey of subjects, with one response per person.** Rejected: it caps the responses at the number
  of people.
- **Absolute dates.** Rejected: the people would pass 25, and the measurements would drift into the past.
