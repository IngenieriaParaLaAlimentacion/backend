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
