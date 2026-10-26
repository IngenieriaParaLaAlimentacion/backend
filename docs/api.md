# API Conventions

## Base URL

All endpoints are prefixed with `/api/v1/`:

```
/api/v1/<module>/<resource>
```

Examples:
```
/api/v1/auth/login
/api/v1/talla-y-peso/measurements
/api/v1/nutrir/plans
```

The only exceptions are the operational probes below.

---

## Health probes

Two public endpoints, outside `/api/v1`, for the platform rather than for clients. Neither
requires authentication, and neither produces traces or HTTP metrics, so they do not skew
the latency dashboards.

| Endpoint | Checks | Used by |
|---|---|---|
| `GET /health` | Nothing: the process answers. | Docker Compose `healthcheck`, post-deploy smoke tests |
| `GET /ready` | PostgreSQL answers `SELECT 1` within `READINESS_DB_TIMEOUT_SECONDS` (default 2 s, connection included). | Railway Healthcheck Path (`railway.toml`) |

`/health` always answers `200` while the process runs, even with the database down:

```json
{ "status": "ok" }
```

`/ready` answers `200` when every check passes:

```json
{ "status": "ready", "checks": { "database": "ok" } }
```

and `503` with type `/errors/service-not-ready` when one fails. The `checks` extension
member names the failing check; the cause (host, driver error, traceback) is logged, never
returned:

```json
{
  "type": "/errors/service-not-ready",
  "title": "Service not ready",
  "status": 503,
  "detail": "One or more dependencies required to serve requests are unavailable.",
  "instance": "/ready",
  "checks": { "database": "unavailable" }
}
```

---

## Authentication

All protected endpoints require a JWT access token in the `Authorization` header:

```
Authorization: Bearer <access_token>
```

Endpoints that do not require authentication (e.g., login, registration) are explicitly marked as public.

---

## Error responses

Errors follow [RFC 7807 — Problem Details for HTTP APIs](https://www.rfc-editor.org/rfc/rfc7807).
**Every** error response — domain errors, validation failures, unrouted paths, wrong
methods, and unhandled exceptions alike — is served as `application/problem+json`
with the same five members.

```json
{
  "type": "/errors/survey-locked",
  "title": "Survey locked",
  "status": 409,
  "detail": "This survey has recorded responses and can no longer be modified.",
  "instance": "/api/v1/surveys/3f2a.../questions"
}
```

| Field | Description |
|---|---|
| `type` | Stable, machine-readable identifier for the problem (`/errors/<slug>`). |
| `title` | Short, human-readable summary of the problem. |
| `status` | HTTP status code. |
| `detail` | Human-readable explanation of this specific occurrence. Always a string. |
| `instance` | The request path where the error occurred. |

### Stability contract

`type` is the stable, machine-readable identifier. Branch on it. It is additive-only:
new values may be added, existing values are not renamed or removed without notice.

`title` and `detail` are human-readable prose for developers and logs.
**Do not display or parse them** — they may be reworded at any time.

The full list of `type` values is generated from the exception registry into
[`errors.md`](errors.md) and [`errors.json`](errors.json). Regenerate with
`poetry run python docs/generate_error_catalog.py`.

### 422 vs 400 for validation errors

FastAPI returns `422 Unprocessable Entity` by default when Pydantic rejects a request body or query parameter. The OpenAPI contract exposed to clients maps these to `400 Bad Request` instead (see `app/core/openapi.py`), which is the semantically correct code for malformed client input.

The response body is the same envelope as any other error, with a string `detail`.
Individual field failures are not reported, except on routes marked
`x-invalid-field-extension`: there the envelope also carries `field`, the name
of the first body field that failed (dotted when nested, such as
`characterization.premises_other`; never its value), so a client can flag the
input without clearing the form.

### Extension members

Some errors carry extra JSON members alongside the canonical five (RFC 7807
extensions) — for example `canonical_subject` on a duplicate-DNI 409. They are
documented per error in [`errors.md`](errors.md).

### Rate limit responses

Rate limited endpoints answer `429` with type `/errors/rate-limited` when a limit is exceeded. The
response carries:

| Where | Field | Description |
|---|---|---|
| Header | `Retry-After` | Seconds to wait before retrying. |
| Header | `X-RateLimit-Limit` | Requests allowed in the window that was exceeded. |
| Header | `X-RateLimit-Remaining` | Always `0` on a 429. |
| Header | `X-RateLimit-Reset` | Epoch seconds at which the caller may retry. |
| Body | `retry_after` | Same value as `Retry-After`, in seconds. |

These headers appear only on the 429. Which endpoints are limited, and how, is described in
[`auth.md`](auth.md#rate-limiting).

## Pagination

Use pagination on all list endpoints that may return unbounded results. Choose the strategy based on the use case:

### Offset-based

Use for paginated views where the user can jump to a specific page (e.g., backoffice tables).

Query params: `?limit=<int>&offset=<int>`

Response envelope:
```json
{
  "data": [...],
  "total": 120,
  "limit": 20,
  "offset": 40
}
```

### Cursor-based

Use for infinite scroll or time-ordered feeds where consistency matters (e.g., mobile lists).

Query params: `?limit=<int>&cursor=<opaque_string>`

Response envelope:
```json
{
  "data": [...],
  "next_cursor": "eyJpZCI6IjEyMyJ9"
}
```

`next_cursor` is `null` when there are no more results.

---

## File exports

List endpoints that support a "Exportar CSV" action expose a sibling `/export` route
(`GET /api/v1/subjects/export`, `GET /api/v1/measurements/export`, …).

- The export accepts **exactly the same filter and sort query params as its listing**,
  reusing the same query dataclass. It takes **no pagination params** and returns the
  whole filtered set.
- Declare the `/export` route **above** any `/{id}` route in the same router, or the
  literal is matched as an id.
- Response is `text/csv; charset=utf-8`, **streamed** (chunked, no `Content-Length`),
  with `Content-Disposition: attachment; filename="<entidad>[_<scope>]_<YYYY-MM-DD>.csv"`
  and `X-Export-Row-Count` stating how many data rows to expect.
- Anything that can fail predictably — validation, a missing parent resource, the row
  count — runs in a **pre-flight** before the response starts, so 4xx still carry a real
  `problem+json` body. Once bytes are on the wire the status is already `200`, and a
  failure aborts the connection instead of completing; clients detect that by reading the
  body rather than linking to the URL.
- The streaming generator owns its own `UnitOfWork`. A `Depends`-provided session is
  closed when the *handler* returns, which is before a streamed body is produced.
- A filter matching nothing returns **`200` with only the header line** — an export that
  matched no rows is a successful export, not an error. Clients disable the button from
  the listing's `total`.
- No cell may contain a newline (`normalize_cell` in `formatters.py`), so a client can
  compare parsed lines against `X-Export-Row-Count`.
- CSV dialect is Argentine/Excel-first: `;` delimiter, decimal comma, `dd/mm/aaaa` dates
  in `America/Argentina/Buenos_Aires`, CRLF, and a leading UTF-8 BOM.

See ADR-0009 for the rationale and `app/services/exporters/csv/` for the implementation.

---

## Request and response format

- All request and response bodies are **JSON** (`Content-Type: application/json`).
- Field names use **snake_case**.
- Dates and timestamps use **ISO 8601** format: `2026-05-18T14:30:00Z`.
- UUIDs are returned as strings.

---

## Endpoint naming

- Use **kebab-case** for URL segments: `/talla-y-peso/`, `/valores-de-hierro/`.
- Use **plural nouns** for resource collections: `/measurements`, `/users`.
- Use **path parameters** for resource identity: `/measurements/{measurement_id}`.
- Avoid verbs in URLs — use the HTTP method to express the action.

```
POST   /api/v1/auth/login
GET    /api/v1/talla-y-peso/measurements
POST   /api/v1/talla-y-peso/measurements
GET    /api/v1/talla-y-peso/measurements/{measurement_id}
DELETE /api/v1/talla-y-peso/measurements/{measurement_id}
```

---

## Admin: change a user's role

```
PATCH /api/v1/admin/users/{user_id}/role
```

Restricted to `admin` and `superadmin`. Changes only `users.role`: status, profile
data and establishment relations are untouched. On a real change the user's refresh
tokens are revoked (they must log in again) and they get an email with the old and new
role. Requesting the role the user already has is a no-op: `200`, no email, sessions
kept.

Request:

```json
{ "role": "analyst" }
```

`role` is one of `field_worker`, `analyst`, `admin`. `superadmin` is never assignable.

Response `200` — same shape as `GET /api/v1/admin/users/{user_id}`:

```json
{
  "id": "6b1f...",
  "email": "ana@example.com",
  "name": "Ana",
  "last_name": "Pérez",
  "role": "analyst",
  "status": "active",
  "locality": null,
  "description": null,
  "contact_phone": null,
  "establishments": []
}
```

Who may change whom (see `docs/auth.md`):

| Actor | May change users with role | To |
|---|---|---|
| `admin` | `field_worker`, `analyst` | `field_worker`, `analyst`, `admin` |
| `superadmin` | `field_worker`, `analyst`, `admin` | `field_worker`, `analyst`, `admin` |

Nobody may change a `superadmin` or their own role.

| Status | `type` | When |
|---|---|---|
| `400` | `/errors/user-is-not-active` | The user is pending (invitation not accepted, field worker not validated) or inactive. |
| `403` | `/errors/role-not-allowed` | Target is a `superadmin`, the actor themselves, or an `admin` changed by an `admin`. Also returned when the caller is not an admin. |
| `404` | `/errors/user-not-found` | No user with that id. |
| `422` | `/errors/validation-failed` | `role` missing or not one of the allowed values (including `superadmin`). |


## Recipe recommendations (Nutrir, #170)

Generation uses OpenRouter → the existing nutrition LP → OpenRouter.
The backend owns quantities, nutrient indicators, permissions and stock changes.
All routes below require Bearer authentication and establishment access. Missing
establishments return 404; denied access returns 403; invalid input uses the
standard 422 problem response. The [recipe OpenAPI contract](recipes.openapi.generated.json) includes request examples.
Regenerate with `poetry run python docs/generate_openapi.py recipes --tag "Recipes V1"`.

| Method | Path (under `/api/v1`) | Result |
|---|---|---|
| POST | `/recipe-recommendations` | 201: one request with 1–3 validated proposals; partial results carry warnings |
| GET | `/establishments/{establishment_id}/recipe-recommendations` | Paginated requests; `chosen_only=true` includes only chosen proposals |
| GET | `/establishments/{establishment_id}/recipes` | Paginated individual proposals, including unchosen alternatives |
| GET | `/recipe-recommendations/{request_id}/proposals/{proposal_id}` | Original saved recipe detail; no scaling or stock check |
| POST | `/recipe-recommendations/{request_id}/proposals/{proposal_id}/choose` | 201 selection; identical replay 200; another choice 409 |
| POST | `/recipe-recommendations/{request_id}/proposals/{proposal_id}/reuse-preview` | 200 read-only rescaled proposal; current stock checked; body `{"children_count":45}` |
| POST | `/recipe-recommendations/{request_id}/proposals/{proposal_id}/reuse` | 201 new selected request, or 200 replay of its client-generated id |

Generation body (no additional fields, no free text):

```json
{"establishment_id":"b45193cb-a2f1-427f-a4d8-adbb596561b0","children_count":30,"meal_type":"lunch"}
```

`children_count` is a strict integer from 1 to 10000. Meal types are `breakfast`,
`lunch`, `snack`, `dinner`; the reference child is always age 7–9. Ingredient
count 5–8 is prompt guidance, not validation. Generation does not reserve stock.
Proposals do not expire; choosing always validates current stock.

A response has `id`, `establishment_id`, `children_count`, `meal_type`,
`created_at`, `proposals`, and nullable `selection`.
Each proposal has `id`, `name`, `portions`, `ingredients` (food_id, name, grams,
quantity in the catalog base unit, unit), `steps`, `indicators` (nutrient adequacy
and macro shares), `gapa_groups`, `unmet_constraints`, `warnings`,
`target_energy_kcal`, `energy_kcal`, explicit `nutrient_adequacy_percent` and
`macronutrient_percent` maps, and nullable `cultural_identity`.
`selection` contains `proposal_id`, `outflow_id`, `user_id`, and `chosen_at`.

Nutritional and energy shortfalls do **not** prevent offering a recipe: clients
must display `unmet_constraints`, energy and warnings. Empty stock, no usable
energy or quantities below stock precision return 409
`/errors/recipes/no-usable-stock` **before any model call**. Foods in litres or
units need the food's density or unit weight from its food equivalences
(ADR-0025); foods without it are excluded and reported, never guessed. All final
quantities are rounded down to stock precision,
and indicators are recalculated from the amounts actually offered.

Choosing has no body. It creates a kitchen outflow and selection atomically.
An identical retry returns the original selection without spending stock again.
A different choice on the same request returns 409
`/errors/recipes/already-chosen`. Insufficient stock at selection uses the same
409 response and food/available/requested fields as manual food outflows.

Before reuse, call `reuse-preview` to display backend-calculated quantities and
indicators without saving a choice or changing stock. Confirmation calls `reuse`,
which checks stock again. Neither endpoint calls the LLM.

Reuse body:

```json
{"id":"72bde9cb-a7b5-48e0-8729-6f91a004d83b","children_count":45}
```

Reuse scales an existing proposal, recalculates indicators, validates current
stock and selects the copy in one transaction without an LLM call. Replaying the
same id and source/count returns 200; changing its meaning returns 409
`/errors/recipes/idempotency-conflict`. The original request stays unchanged.

A history item from `/establishments/{id}/recipe-recommendations` is a request
containing its saved proposals (1–3 for generation, one for reuse).
`chosen_only=true` filters both requests and their proposals to the chosen ones.
For a flat list, use `GET /establishments/{id}/recipes`: each item contains one
`proposal` plus `request_id`, `establishment_id`, `meal_type`, `created_at` and
`chosen`. It includes unchosen alternatives unless `chosen_only=true`; three
requests with three proposals each produce nine items. Both lists use standard
pagination. Read any original snapshot without scaling or stock validation via
`GET /recipe-recommendations/{request_id}/proposals/{proposal_id}`. Preview is
only for rescaling and checking current stock before reuse; it does not replace
reading a saved recipe. Viewing old recipes never invokes AI.

Field workers **and analysts** require an approved `user_establishments` relation
for the establishment. “Access” and “subscription” describe that same approved
relation in this workflow; there is no second paid subscription or permission.
Admins and superadmins may access any establishment.

Request-level `user_id` and `prompt_version` were removed before the migration
was applied: no feature consumes them. Selection `user_id` is retained to
attribute the actual stock outflow. Prompt version is recorded in generation
failure logs, where it supports diagnosis; it does not promise reproducibility.
Proposal `position` remains an internal zero-based display order for history.

AI generation and receipt extraction (`POST /food-intakes/from-photo`) share a
per-authenticated-user moving-window quota, configured by `RATE_LIMIT_AI_USER`
(default `20/hour`). Users behind the same IP have separate quotas. Requests
past the quota return `429 /errors/rate-limited` and `Retry-After`, before model
calls. Redis-backed counting uses the existing in-process fallback during an
outage (replicas count separately while degraded). Non-AI history, preview,
selection and reuse do not consume this quota.

Reuse/preview return specific 409 errors with `food_id` and `ingredient`:
`/errors/recipes/ingredient-unavailable` when a catalog ingredient is missing,
`/errors/recipes/ingredient-unit-changed` when its base unit changed, and
`/errors/recipes/scale-too-small` when rounding would drop a required ingredient.
Missing gram factors or zero usable energy still return `no-usable-stock`.

Culture is read from `characterization.cultural_identities` and optional
`characterization.cultural_identities_other`. Edit it through the existing ficha
`PUT /establishments/{establishment_id}/characterization` (full profile replacement),
using its admin/superadmin or approved field-worker permissions. The shared
profile catalog includes Paraguayan and Bolivian alongside its existing codes.
Generation includes the last ten chosen recipes, asks for cultural inspiration when viable, and permits ordinary dishes when stock cannot support
it. Cultural inspiration never adds ingredients or alters calculated quantities.

Normal generation uses two logical model calls, with at most one repair call
for invalid/duplicate candidate sets. Each completion shares at most two
inference attempts across approved free models, with one total deadline.
Invalid AI content returns the standard
`/errors/recipes/generation-failed` domain error; no incomplete proposals are saved.
History uses the standard `items`, `total`, `page`, `page_size`, `total_pages`
envelope, ordered by date and id descending. Ingredient amounts and steps are
immutable snapshots; prompt templates are versioned in the repository.

Recipes convert stock to grams with the shared conversion module (ADR-0025).
Kilogram conversions are exact and missing density or unit-weight factors are
never guessed.

Recipe generation has a total service budget, configured by
`RECIPE_GENERATION_TIMEOUT_SECONDS` (90 seconds by default). It includes context
reads, LP work, all model attempts, retry waits, fallback and persistence. On
expiry the task is cancelled, the transaction is rolled back and the API returns
`504 /errors/recipes/generation-timeout`. Authentication, upload/transport and
proxy timeouts are outside this service budget. Configure the deployment proxy
and client timeout above that budget; the repository does not establish the
live gateway's timeout. This deadline does not add generation idempotency.

OpenRouter output is capped by `OPENROUTER_MAX_OUTPUT_TOKENS` (8192 by default).
Model IDs are taken directly from the workload environment arrays. Every request
requires strict structured outputs, restricts hosting providers, denies provider
data collection and limits prompt, completion, request and image prices to zero.
There is no catalogue fetch or local metadata cache. Select suitable free models
operationally; the gateway enforces the request constraints.
Empty AI configuration leaves inference unavailable while non-AI routes still run.

Recipe generation provider usage limits return `429 /errors/ai/quota-exhausted`,
distinct from the inbound caller limit `429 /errors/rate-limited`. A known, validated provider delay
appears in both `Retry-After` and integer `retry_after`; otherwise both are absent.
No reset time or daily allowance is promised. Missing credentials, no eligible
endpoint or exhausted temporary failures return `503 /errors/ai/unavailable`.
Neither error exposes provider prose. Clients must not automatically resubmit.

Receipt success remains an HTTP 200 proposal without `needs_review`. All lines
require local review before confirmation. Extra AI response fields are ignored;
invalid required extraction structure still returns
an empty proposal with a manual-entry hint. Provider quota, unavailable endpoints
and missing AI configuration use that same HTTP 200 manual fallback, preserving
the existing receipt UX. The app opens the review form directly with the captured
photo. Inbound caller rate limits remain HTTP 429. Manual intake and confirmation
remain usable without inference. The entire receipt proposal service has a
60-second budget (`RECEIPT_GENERATION_TIMEOUT_SECONDS`); expiry rolls back and
returns the same manual fallback.

Receipts and recipes share one lazy OpenRouter client per application instance,
closed at lifespan shutdown. Logs contain controlled model, attempt and error-type
metadata; response text, prompts, images, keys and raw provider error bodies are
excluded. The Spanish quantity detector covers common numeric/word amounts,
fractions and ingredient units while allowing cooking times and temperatures;
it remains a heuristic, not a general natural-language guarantee.

Generation aims for 2–3 alternatives but returns even one independently valid
recipe. Invalid candidate entries are skipped; a selection repair is attempted
only when there are no usable candidates. Writing is validated per recipe:
malformed entries, missing/unknown IDs, unsupported culture, changed ingredient
references, prose quantities and duplicate preparations do not discard valid
siblings. There is no extra model call to fill the result count or repair writing.
No valid final recipe still returns 502 and saves nothing.

The existing per-proposal `warnings` list also carries these stable codes:
- `recipes/fewer-alternatives`: fewer valid alternatives than expected survived.
- `recipes/cultural-unavailable`: cultural identities were configured but none
  of the final recipes has a cultural tag. The model's cultural_dish_viable flag
  does not control rejection or trigger another call.

Warnings are attached to every surviving proposal, persisted with its snapshot
and returned in history/detail/reuse. They describe recommendation availability,
not missing nutrient data. Clients must display them separately from nutrition
metadata warnings. Cultural inspiration remains optional even when the model
claims a cultural dish was viable.
