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
Individual field failures are not reported.

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

Generation uses Gemini → the existing nutrition LP → Gemini.
The backend owns quantities, nutrient indicators, permissions and stock changes.
All routes below require Bearer authentication and establishment access. Missing
establishments return 404; denied access returns 403; invalid input uses the
standard 422 problem response. The [recipe OpenAPI contract](recipes.openapi.generated.json) includes request examples.
Regenerate with `poetry run python docs/generate_openapi.py recipes --tag "Recipes V1"`.

| Method | Path (under `/api/v1`) | Result |
|---|---|---|
| POST | `/recipe-recommendations` | 201: one request with 2–3 proposals |
| GET | `/establishments/{establishment_id}/recipe-recommendations` | Paginated requests; `chosen_only=true` includes only chosen proposals |
| POST | `/recipe-recommendations/{request_id}/proposals/{proposal_id}/choose` | 201 selection; identical replay 200; another choice 409 |
| POST | `/recipe-recommendations/{request_id}/proposals/{proposal_id}/reuse-preview` | 200 read-only rescaled proposal; current stock checked; body `{"children_count":45}` |
| POST | `/recipe-recommendations/{request_id}/proposals/{proposal_id}/reuse` | 201 new selected request, or 200 replay of its client-generated id |
| GET | `/cultural-identities` | Closed list of supported cultural identity codes |
| GET | `/establishments/{establishment_id}/cultural-identities` | Configured identities (possibly empty) |
| PUT | `/establishments/{establishment_id}/cultural-identities` | Admin-only replacement, 200 |
| PUT | `/food-catalog/foods/{food_id}/gram-conversion` | Admin-only grams per litre/unit; kilograms always use 1000 |

Generation body (no additional fields, no free text):

```json
{"establishment_id":"b45193cb-a2f1-427f-a4d8-adbb596561b0","children_count":30,"meal_type":"lunch"}
```

`children_count` is a strict integer from 1 to 10000. Meal types are `breakfast`,
`lunch`, `snack`, `dinner`; the reference child is always age 7–9. Ingredient
count 5–8 is prompt guidance, not validation. Generation does not reserve stock.
Proposals do not expire; choosing always validates current stock.

A response has `id`, `establishment_id`, `children_count`, `meal_type`, `user_id`,
`created_at`, `prompt_version`, `proposals`, and nullable `selection`.
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
units require a reviewed gram conversion; absent conversions are excluded and
reported, never guessed. Configure with `{"grams_per_base_unit":50}` (e.g. one
egg); `null` clears it. All final quantities are rounded down to stock precision,
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

Culture replacement body: `{"identities":["paraguayan","bolivian"]}`. The initial
closed list is Paraguayan and Bolivian; multiple identities and an empty list
are supported. Generation includes the last ten chosen recipes, asks for cultural
inspiration when viable, and permits ordinary dishes when stock cannot support
it. Cultural inspiration never adds ingredients or alters calculated quantities.

Normal generation uses two logical model calls, with at most one repair call
for invalid/duplicate candidate sets. Transport retries and fallback reuse the
existing Gemini policy. Invalid/failing AI returns the standard
`/errors/recipes/generation-failed` domain error; no incomplete proposals are saved.
History uses the standard `items`, `total`, `page`, `page_size`, `total_pages`
envelope, ordered by date and id descending. Ingredient amounts and steps are
immutable snapshots; prompt templates are versioned in the repository.
