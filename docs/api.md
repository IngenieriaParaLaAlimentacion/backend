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
with the same members.

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
| `reason` | Optional machine-readable sub-code distinguishing variants of one `type`. |
| `errors` | Present on validation failures only — see below. |

### Stability contract

`type` is the stable, machine-readable identifier. Branch on it. It is additive-only:
new values may be added, existing values are not renamed or removed without notice.

`title` and `detail` are human-readable prose for developers and logs.
**Do not display or parse them** — they may be reworded at any time. Per-field
failures are in `errors[]`.

The full list of `type` values is generated from the exception registry into
[`errors.md`](errors.md) and [`errors.json`](errors.json). Regenerate with
`poetry run python docs/generate_error_catalog.py`.

### Validation errors

A request that fails schema validation returns `422 Unprocessable Entity` with a
string `detail` and a per-field `errors[]` array. Submitted values are never echoed
back.

```json
{
  "type": "/errors/validation-failed",
  "title": "Validation failed",
  "status": 422,
  "detail": "The request contains invalid or missing fields.",
  "instance": "/api/v1/auth/login",
  "errors": [
    {"pointer": "/body/email", "detail": "Field required", "code": "missing"}
  ]
}
```

`pointer` names the offending field: `loc[0]` is the request part
(`/body/...`, `/query/...`, `/path/...`) and list indices appear as segments
(`/body/tags/1`).

### Sub-codes

Where one `type` covers several distinguishable triggers with the same client
recovery, the specific trigger travels in an optional `reason` member — for
example `/errors/survey-locked` with `"reason": "question_removed"` vs
`"reason": "has_responses"`. Branch on `type` first; use `reason` only to refine
the message you show.

### Extension members

Some errors carry extra JSON members alongside the canonical five (RFC 7807
extensions) — for example `canonical_subject` on a duplicate-DNI 409. They are
documented per error in [`errors.md`](errors.md).

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
