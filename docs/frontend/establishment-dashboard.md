# Frontend handoff — Establishment (comedor) dashboard

## Context
Dedicated screen showing the metrics of a **single comedor**: how many subjects attend it,
their anthropometric averages, the establishment-wide alert banner, the list of subjects,
and the list of enrolled field workers.

All three endpoints require `Authorization: Bearer <access_token>` and are restricted to
**admin / analyst / superadmin**. A `field_worker` token gets `403`; missing or invalid
token gets `401`. An unknown `establishment_id` gets `404` on all three.

Base path: `/api/v1`.

## Glossary (ES → API field)
- Comedor / establecimiento → `establishment` · Sujeto → `subject` · Relevador → field worker
- Cantidad de sujetos que asisten → `metrics.subject_count`
- Talla → `height_cm` (cm) · Peso → `weight_kg` (kg) · IMC → `bmi` · Edad → `age_months` (months)
- Estado de alerta → `alert_status` · Estado nutricional → `nutritional_status`
- Fecha del relevamiento → `measured_at` (ISO-8601 datetime, UTC)
- Ubicación → `city` + `province` (+ `formatted_address`, `latitude`/`longitude`)

---

## 1. Establishment dashboard (metrics + alert banner)
`GET /api/v1/establishments/{establishment_id}/dashboard`

No query params.

### Response `200` — `EstablishmentDashboardResponse`
```json
{
  "establishment": {
    "id": "uuid",
    "name": "Comedor La Esperanza",
    "formatted_address": "Calle 1 123, La Plata",
    "latitude": -34.9,
    "longitude": -57.9,
    "place_id": "ChIJ...",
    "city": "La Plata",
    "province": "Buenos Aires"
  },
  "has_data": true,
  "metrics": {
    "subject_count": 42,
    "measurement_count": 137,
    "last_measured_at": "2026-07-20T10:00:00Z",
    "avg_height_cm": 118.4,
    "avg_weight_kg": 23.1,
    "avg_bmi": 16.5,
    "avg_age_months": 87
  },
  "alert_status": {
    "severity": "critical",
    "dominant_status": "normal",
    "total_evaluated": 42,
    "at_risk_count": 11,
    "at_risk_percentage": 26.19,
    "distribution": [
      { "status": "normal",          "severity": null,       "count": 31, "percentage": 73.81 },
      { "status": "wasted",          "severity": "high",     "count":  6, "percentage": 14.29 },
      { "status": "overweight",      "severity": "medium",   "count":  3, "percentage":  7.14 },
      { "status": "severely_wasted", "severity": "critical", "count":  2, "percentage":  4.76 }
    ]
  }
}
```

### ⚠️ Empty state — read this before rendering anything
When the comedor has no measurements at all, **`has_data` is `false` and every average is
`null`, not `0`**:

```json
{
  "establishment": { "...": "..." },
  "has_data": false,
  "metrics": {
    "subject_count": 0,
    "measurement_count": 0,
    "last_measured_at": null,
    "avg_height_cm": null,
    "avg_weight_kg": null,
    "avg_bmi": null,
    "avg_age_months": null
  },
  "alert_status": {
    "severity": null,
    "dominant_status": null,
    "total_evaluated": 0,
    "at_risk_count": 0,
    "at_risk_percentage": null,
    "distribution": []
  }
}
```

**Branch on `has_data`, not on `subject_count === 0`,** and show "Sin datos disponibles"
instead of the metric tiles. Do not run the numbers through a formatter that turns `null`
into `0` — displaying `0 kg` / `IMC 0` for an unmeasured comedor is the exact bug this
shape exists to prevent. `establishment` is always populated, so the header (name,
ubicación) renders normally even in the empty state.

### Field notes
| Field | Notes |
|-------|-------|
| `metrics.subject_count` | distinct subjects **measured at this comedor** |
| `metrics.measurement_count` | total historical measurements, including repeat visits |
| `metrics.avg_*` | computed over **one row per subject** — their most recent measurement here. A subject measured 10 times does not skew the average. Already rounded to 2 decimals |
| `metrics.avg_age_months` | whole months, **age at the time of measurement** (not current age). Divide by 12 for years |
| `alert_status.severity` | `critical` \| `high` \| `medium` \| `null`. See below |
| `alert_status.dominant_status` | most common status; ties break towards the more severe one |
| `alert_status.at_risk_count` | subjects whose status is **not** `normal` |
| `distribution[].percentage` | share of `total_evaluated`, 2 decimals. Sums to ~100 (rounding) |

### How to render the alert banner
`severity` is the **worst severity present among the subjects**, not an average and not a
prevalence threshold. One critical case sets the banner to `critical` even if 98% of
subjects are `normal` — deliberately conservative.

**So do not show `severity` on its own.** Pair it with the counts, e.g.
`"Estado crítico — 2 de 42 sujetos en emaciación grave"`. `distribution` and
`at_risk_percentage` exist precisely so the banner can be qualified. If the product later
wants a threshold ("critical only above 10%"), that is a backend change — do not
reimplement the rule on the client.

`severity: null` means every subject is `normal` → render a neutral/OK banner, not an
error state.

---

## 2. Subjects attending the comedor
`GET /api/v1/establishments/{establishment_id}/subjects`

Query params (all optional):

| Param | Type | Notes |
|-------|------|-------|
| `page` | int (≥1, default 1) | |
| `page_size` | int (1–100, default 20) | |
| `search` | string (≤100) | partial case-insensitive match on nombre/apellido; exact match on DNI when the term is all digits |
| `sort_order` | enum | `measured_at_desc` (default) `measured_at_asc` `name_asc` `name_desc` `bmi_desc` `bmi_asc` `age_desc` `age_asc` |

`name_asc`/`name_desc` sort by **apellido** (`last_name`). `age_*` sort by `birth_date`.

### Response `200` — `PaginatedResponse<EstablishmentSubjectListItem>`
```json
{
  "items": [
    {
      "id": "uuid",
      "dni": 45123456,
      "name": "Ana",
      "last_name": "Gómez",
      "sex": "female",
      "birth_date": "2018-03-11",
      "age_months": 100,
      "measurement_count": 4,
      "nutritional_status": "wasted",
      "latest_measurement": {
        "id": "uuid",
        "measured_at": "2026-07-20T10:00:00Z",
        "weight_kg": 21.0,
        "height_cm": 118.0,
        "bmi": 15.08,
        "alerts": [
          { "alert_type": "wasted", "severity": "high", "detail": "BMI-for-age z-score -2.31 < -2 SD: moderate acute malnutrition (emaciación)." }
        ]
      }
    }
  ],
  "total": 42,
  "page": 1,
  "page_size": 20,
  "total_pages": 3
}
```

### Field notes
- **`id` is the SUBJECT id**, not the measurement id — this is what you navigate with.
  `latest_measurement.id` is a different id and is only useful for deep-linking a specific
  measurement.
- The first five fields (`id`, `dni`, `name`, `last_name`, `sex`) are exactly the shape of
  the general subjects listing (`GET /api/v1/subjects`), so an existing subject row/table
  component can be reused as-is and progressively enhanced with the extra fields.
- `latest_measurement` is **never null** here: a subject only appears in this list because
  they have at least one measurement at this comedor.
- `measurement_count` counts measurements **at this comedor only**, not the subject's
  global history.
- `alerts` may be empty (`[]`) — that is the `normal` case. At most one alert per
  measurement today, but treat it as a list.
- `nutritional_status` is derived from `latest_measurement.alerts`; prefer it over
  re-deriving the status from `alerts` on the client.

### Navigating to a subject's detail
Use the existing endpoints with the row's `id`:
- `GET /api/v1/subjects/{subject_id}` → subject record, **now including
  `nutritional_status` and `latest_measurement`** (see section 4)
- `GET /api/v1/subjects/{subject_id}/measurements/evolution` → growth chart
  (see `measurements-viewing.md`)

Note the evolution endpoint returns the subject's measurements across **all** comedores,
not just this one.

---

## 4. Subject detail — alert badge outside the comedor view
`GET /api/v1/subjects/{subject_id}`

Available to **any authenticated role**. Additive change: every field the endpoint returned
before is unchanged, with two new ones appended. Do **not** call
`/measurements/evolution` just to read a badge — it returns the subject's whole unpaginated
history.

### Response `200` — `SubjectDetailResponse`
```json
{
  "id": "uuid",
  "dni": 45123456,
  "name": "Ana",
  "last_name": "Gómez",
  "sex": "female",
  "birth_date": "2018-03-11",
  "is_rural": false,
  "is_indigenous": false,
  "nutritional_status": "wasted",
  "latest_measurement": {
    "id": "uuid",
    "measured_at": "2026-07-20T10:00:00Z",
    "weight_kg": 21.0,
    "height_cm": 118.0,
    "bmi": 15.08,
    "establishment": { "id": "uuid", "name": "Comedor Norte", "city": "La Plata", "province": "Buenos Aires" },
    "alerts": [ { "alert_type": "wasted", "severity": "high", "detail": "..." } ]
  }
}
```

### ⚠️ Three things to get right

**1. Never measured ⇒ both fields are `null`.**
```json
{ "...": "...", "nutritional_status": null, "latest_measurement": null }
```
Subjects are not tied to a comedor, so a subject with zero measurements is a perfectly
normal record. `null` is **not** `normal` — render "sin datos", not a green badge. `normal`
means *measured and healthy*.

**2. This is the subject's GLOBAL latest measurement**, across every comedor — unlike
section 2, where `nutritional_status` is scoped to the comedor being viewed. The same
subject can legitimately show `wasted` in Comedor A's list and `normal` here, if their most
recent reading was taken somewhere else. That is why `latest_measurement.establishment` is
included: use it to label the badge ("último relevamiento — Comedor Norte, 20/07") so the
difference reads as information rather than a bug.

**3. `POST` and `PATCH /subjects/{id}` do NOT return these fields.** They still return the
plain `SubjectResponse`. Only `GET /subjects/{subject_id}` is enriched — don't type them as
one shared model.

---

## 3. Field workers (relevadores) enrolled in the comedor
`GET /api/v1/establishments/{establishment_id}/field-workers`

Query params (all optional):

| Param | Type | Notes |
|-------|------|-------|
| `page` | int (≥1, default 1) | |
| `page_size` | int (1–100, default 20) | |
| `search` | string (≤100) | partial case-insensitive match on nombre, apellido or email |
| `relation_status` | enum | `approved` (**default**) \| `pending` \| `rejected` |

### Response `200` — `PaginatedResponse<EstablishmentFieldWorkerListItem>`
```json
{
  "items": [
    {
      "id": "uuid",
      "name": "Juan",
      "last_name": "Pérez",
      "email": "juan@ejemplo.com",
      "user_status": "active",
      "relation_status": "approved",
      "measurement_count": 58,
      "last_measured_at": "2026-07-20T10:00:00Z"
    }
  ],
  "total": 3,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

### Field notes
- The list is **enrollment-based**, not activity-based. By default it shows users with an
  `approved` relation to the comedor. A user who recorded measurements here but is enrolled
  elsewhere will **not** appear; conversely an approved user with zero measurements will
  appear with `measurement_count: 0` and `last_measured_at: null`.
- `user_status` (account state) and `relation_status` (enrollment at this comedor) are
  independent — an `active` user can be `pending` here. Show both if the screen is for
  admins.
- `measurement_count` and `last_measured_at` are scoped to **this comedor**.

---

## Enums

| Enum | Values |
|------|--------|
| `nutritional_status`, `distribution[].status` | `normal` `overweight` `obese` `wasted` `severely_wasted` `underweight` `severe_underweight` — plus `null` on `GET /subjects/{id}` when never measured |
| `severity` (alert + distribution) | `critical` `high` `medium` — plus `null` for `normal` |
| `alert_type` (inside `alerts`) | `severely_wasted` `wasted` `overweight` `obese` `severe_underweight` `underweight` |
| `sex` | `male` `female` |
| `user_status` | `active` `inactive` `pending_validation` |
| `relation_status` | `approved` `pending` `rejected` |

`underweight` / `severe_underweight` only occur for subjects over 19 years old (adult BMI
cutoffs); `wasted` / `severely_wasted` only for under-19s (WHO BMI-for-age z-score). Both
sets can coexist in one comedor if it serves adults and children — handle all seven values.

Suggested severity → colour: `critical` = red, `high` = orange, `medium` = amber,
`null`/`normal` = green or neutral.

---

## Screen assembly notes

**Loading.** The three endpoints are independent; fire them in parallel. The dashboard call
is the one that gates the empty state — the other two can render skeletons meanwhile.

**Back navigation (preserving filters + scroll).** No backend support needed. The comedores
panel (`GET /api/v1/establishments`) accepts `search`, `city`, `province`, `sort_order`,
`page`, `page_size` and is idempotent, so push those into the URL query string on the
panel screen and the browser restores them on back.

**Establishment header.** Available fields are `name`, `formatted_address`, `city`,
`province`, `latitude`/`longitude`. **There is no `responsable` field on the
establishment** — the data model has no such column. The closest available context is the
field workers list (section 3). If the product needs a formally assigned responsable, that
is a schema change and a separate ticket.

**Repeat visits.** A subject appearing once in the list may have several measurements
(`measurement_count > 1`). The listed values are always the most recent ones; use the
evolution endpoint for history.

---

## Error shape (RFC 7807 `application/problem+json`)
```json
{
  "type": "/errors/establishment-not-found",
  "title": "Establishment not found",
  "status": 404,
  "detail": "...",
  "instance": "/api/v1/establishments/{id}/dashboard"
}
```

| Status | When | Suggested handling |
|--------|------|--------------------|
| `401` | missing/expired token | re-auth |
| `403` | `field_worker` token | hide the whole feature for non admin/analyst |
| `404` | unknown `establishment_id` | "Comedor no encontrado", back to panel |
| `422` | malformed query param (bad UUID, bad enum, `page_size` > 100) | client bug — validate before sending |

Note `404` (comedor does not exist) and the empty state (`has_data: false`, comedor exists
but has no data) are **different situations** and must render differently.
