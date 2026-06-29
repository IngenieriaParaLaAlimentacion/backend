# Frontend handoff — Viewing anthropometric measurements

## Context
Backend REST API for the nutritional management platform. The mobile/web clients consume
this API; they never call external services directly. This feature lets an
**Admin/Professional (analyst)** browse recorded weight/height measurements, filter them,
and view a single child's growth evolution chart.

All endpoints require `Authorization: Bearer <access_token>` and are restricted to roles
**admin / analyst / superadmin**. A `field_worker` token receives `403`. Missing/invalid
token → `401`.

Base path: `/api/v1`.

## Glossary (ES → API field)
- Peso → `weight_kg` (float, kg) · Talla → `height_cm` (float, cm) · IMC → `bmi`
- Fecha del relevamiento → `measured_at` (ISO-8601 datetime, UTC)
- Sujeto → `subject` · Comedor → `establishment` · Ciudad → `establishment.city`
- Provincia → `establishment.province` · Responsable de relevamiento → `responsible`
- Edad → derived from `subject.birth_date` (filtered by **current** age in years)

---

## 1. List measurements
`GET /api/v1/measurements`

Query params (all optional):

| Param | Type | Notes |
|-------|------|-------|
| `page` | int (≥1, default 1) | |
| `page_size` | int (1–100, default 20) | |
| `subject_id` | UUID | filter by subject |
| `establishment_id` | UUID | filter by comedor |
| `city` | string | ciudad (case-insensitive exact) |
| `province` | string | provincia (case-insensitive exact) |
| `responsible_id` | UUID | responsable de relevamiento |
| `measured_from` | datetime (ISO) | inclusive lower bound on `measured_at` |
| `measured_to` | datetime (ISO) | inclusive upper bound on `measured_at` |
| `min_age` | int (0–150) | min current age in years |
| `max_age` | int (0–150) | max current age in years |
| `sort_order` | enum | `date_desc` (default) `date_asc` `weight_desc` `weight_asc` `height_desc` `height_asc` |

Returns `400` if `min_age > max_age` or `measured_from > measured_to`.

### Response `200` — `PaginatedResponse<MeasurementListItem>`
```json
{
  "items": [
    {
      "id": "uuid",
      "measured_at": "2026-03-01T10:00:00Z",
      "weight_kg": 12.4,
      "height_cm": 86.0,
      "bmi": 16.8,
      "subject": { "id": "uuid", "dni": 12345678, "sex": "female", "name": "Ana", "last_name": "Pérez", "birth_date": "2023-01-15" },
      "establishment": { "id": "uuid", "name": "Comedor Norte", "city": "La Plata", "province": "Buenos Aires" },
      "responsible": { "id": "uuid", "name": "Juan", "last_name": "Gómez" },
      "alerts": [ { "alert_type": "underweight", "severity": "high", "detail": "..." } ]
    }
  ],
  "total": 42,
  "page": 1,
  "page_size": 20,
  "total_pages": 3
}
```
`alerts` may be empty. `alert_type` ∈ `severely_wasted|wasted|overweight|obese|severe_underweight|underweight`; `severity` ∈ `critical|high|medium` — use these to highlight risk rows ("detectar situaciones de riesgo"). `sex` ∈ `male|female`.

**UI mapping (CA1–CA3 + Notes):** a table with columns Peso / Talla / Fecha (CA2) plus
Sujeto / Comedor / Responsable; filter controls for every query param; column/sort control
via `sort_order`; server-side pagination via `page` / `total_pages`.

---

## 2. Subject evolution (growth chart) — CA4
`GET /api/v1/subjects/{subject_id}/measurements/evolution`

No pagination. Points are ordered chronologically (ascending `measured_at`).

### Response `200` — `SubjectEvolutionResponse`
```json
{
  "subject": { "id": "uuid", "dni": 12345678, "sex": "female", "name": "Ana", "last_name": "Pérez", "birth_date": "2023-01-15" },
  "points": [
    { "measured_at": "2026-01-10T09:00:00Z", "weight_kg": 11.0, "height_cm": 82.0, "bmi": 16.4, "alerts": [] },
    { "measured_at": "2026-03-01T10:00:00Z", "weight_kg": 12.4, "height_cm": 86.0, "bmi": 16.8, "alerts": [] }
  ]
}
```
`404` if the subject does not exist.

**UI mapping:** plot `weight_kg` and `height_cm` (and optionally `bmi`) against
`measured_at` as line charts to show nutritional trends. Empty `points` ⇒ "no
measurements yet".

---

## 3. (Not implemented) Single measurement detail
A dedicated `GET /api/v1/measurements/{measurement_id}` was scoped as optional and is **not
implemented**. The listing item already carries everything needed for a row-detail view.
Request it if a standalone detail screen is required.

## Error shape (RFC 7807 `application/problem+json`)
```json
{ "type": "/errors/...", "title": "...", "status": 400, "detail": "...", "instance": "/api/v1/measurements" }
```
Handle `401` (re-auth), `403` (hide feature for non-admin/analyst), `404`, `400`
(inconsistent filters), `422` (malformed query param types).
