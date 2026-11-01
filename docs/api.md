# API Conventions

General conventions that apply to every endpoint of the API: URLs, authentication, formats, errors, pagination and exports.

The contract of each endpoint (parameters, bodies and responses) is not repeated here. It lives in:

- The interactive documentation (Swagger UI) that the backend serves at `/docs`, generated from the code. Locally: `http://localhost:8080/docs`.
- Guides for features whose behavior needs more than the schema: [`csv-exports.md`](csv-exports.md) and [`subjects-offline-sync.md`](subjects-offline-sync.md).

## Base URL

All endpoints are prefixed with the API version, currently `/api/v1/`:

```
/api/v1/<resource>
```

Examples:
```
/api/v1/auth/login
/api/v1/measurements
/api/v1/food-intakes
```

The only exceptions are the operational probes below.

---

## Health probes

Two public endpoints, outside the versioned prefix, for the platform rather than for clients. Neither
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

List endpoints that may return unbounded results are paginated by page.

Query params:

| Param | Type | Default | Notes |
|---|---|---|---|
| `page` | integer ≥ 1 | `1` | Page number, starting at 1. |
| `page_size` | integer 1–100 | `20` | Results per page. |

Response envelope:

```json
{
  "items": [...],
  "total": 120,
  "page": 3,
  "page_size": 20,
  "total_pages": 6
}
```

`total_pages` is `0` when there are no results.

---

## File exports

List endpoints that support an "Exportar CSV" action expose a sibling `/export` route
(`GET /api/v1/subjects/export`, `GET /api/v1/measurements/export`, …).

- The export accepts the same filter and sort query params as its listing, takes no
  pagination params, and returns the whole filtered set.
- The response is `text/csv; charset=utf-8`, streamed, with a
  `Content-Disposition: attachment` filename and an `X-Export-Row-Count` header stating how
  many data rows to expect.
- A filter matching nothing returns `200` with only the header line: an export that matched
  no rows is a successful export, not an error.

Using the exports from a client: [`csv-exports.md`](csv-exports.md).
Dialect, streaming and implementation: [ADR-0009](adr/0009-generic-csv-exporter-for-listings.md).

---

## Request and response format

- All request and response bodies are **JSON** (`Content-Type: application/json`).
- Field names use **snake_case**.
- Dates and timestamps use **ISO 8601** format: `2026-05-18T14:30:00Z`.
- UUIDs are returned as strings.

---

## Endpoint naming

- Use **kebab-case** for URL segments: `/food-catalog/`, `/food-intakes/`.
- Use **plural nouns** for resource collections: `/measurements`, `/users`.
- Use **path parameters** for resource identity: `/subjects/{subject_id}`.
- Avoid verbs in URLs — use the HTTP method to express the action.

```
POST   /api/v1/auth/login
GET    /api/v1/subjects
POST   /api/v1/subjects
GET    /api/v1/subjects/{subject_id}
PATCH  /api/v1/subjects/{subject_id}
```
