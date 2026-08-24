# Frontend handoff — Exporting listings to CSV

## Context
Adds a **"Exportar CSV"** action to five screens: Sujetos, Establecimientos, Mediciones,
Encuestas and the Detalle de Establecimiento (sujetos que asisten). The export always
reflects what the user is looking at: same filters, same sort order, every matching row
rather than the current page.

All five endpoints require `Authorization: Bearer <access_token>` and are restricted to
roles **admin / analyst / superadmin**. A `field_worker` token receives `403`;
missing/invalid token → `401`. Note this is stricter than two of the listings:
`GET /establishments` is public and `GET /subjects` allows any role, but their exports
are not.

Base path: `/api/v1`.

---

## The five endpoints

| Screen | Endpoint | Query params | Filename |
|---|---|---|---|
| Sujetos | `GET /subjects/export` | same as `GET /subjects` | `sujetos_2026-08-24.csv` |
| Establecimientos | `GET /establishments/export` | same as `GET /establishments` | `establecimientos_2026-08-24.csv` |
| Mediciones | `GET /measurements/export` | same as `GET /measurements` | `mediciones_2026-08-24.csv` |
| Encuestas | `GET /surveys/export` | same as `GET /surveys` | `encuestas_2026-08-24.csv` |
| Detalle de Establecimiento | `GET /establishments/{establishment_id}/subjects/export` | same as its listing | `sujetos_comedor-la-union_2026-08-24.csv` |

**Send the same query string you sent the listing**, minus `page` and `page_size` — those
are rejected as unknown params only if you validate strictly; the backend ignores them.
There is no separate "export filters" contract to build.

`GET /subjects/export` and `GET /measurements/export` return `400` on an inverted range,
exactly like their listings (`birth_date_from > birth_date_to`, `min_age > max_age`,
`measured_from > measured_to`).
`GET /establishments/{id}/subjects/export` returns `404` for an unknown establishment.

---

## Response

```
HTTP/1.1 200 OK
Content-Type: text/csv; charset=utf-8
Content-Disposition: attachment; filename="sujetos_2026-08-24.csv"

Nombre;Documento;Fecha de nacimiento;Último relevamiento
Ana Alvarez;20000001;14/03/2015;14/03/2026 07:30
```

The body is a complete file, not a JSON envelope. Trigger the download from the blob:

```js
const res = await fetch(`/api/v1/subjects/export?${params}`, { headers });
const blob = await res.blob();
const url = URL.createObjectURL(blob);
const a = Object.assign(document.createElement("a"), { href: url, download: filename });
a.click();
URL.revokeObjectURL(url);
```

Prefer the server's filename, parsed out of `Content-Disposition`. It already carries the
entity and the export date (and the establishment slug on the detail export), so you do
not need to build one client-side.

> If the app is ever served from a different origin than the API, reading
> `Content-Disposition` from JS requires the backend to send
> `Access-Control-Expose-Headers: Content-Disposition`. Today the API ships no CORS
> middleware at all, so clients are same-origin/proxied and this is a non-issue — flag it
> to backend if that changes.

---

## Empty results

A filter matching nothing returns **`200` with only the header line** — a valid, openable
file with zero data rows. The backend does not error on this.

Drive the button state from the listing you already have: **disable "Exportar CSV" when
the listing response's `total` is `0`**, and show the "no hay datos para exportar"
message there. Do not call the export endpoint to find out whether there is data.

---

## CSV format (read this before testing in Excel)

The file is tuned for **Excel in a Spanish locale**, which is how coordinators will open
it:

| Aspect | Value | Why |
|---|---|---|
| Delimiter | `;` | Excel es-AR splits on `;`, not `,` |
| Decimals | comma — `18,52` | matches the locale; unambiguous because the delimiter is `;` |
| Dates | `14/03/2015` | `dd/mm/aaaa` |
| Timestamps | `14/03/2026 07:30` | converted to `America/Argentina/Buenos_Aires` (the API's JSON is UTC — **the CSV is not**) |
| Encoding | UTF-8 **with BOM** | without it Excel mangles `Ñ`, `ó`, `ú` |
| Line endings | CRLF | RFC 4180 |

Opening the file by double-clicking in Excel es-AR should need no import wizard, and
numeric columns should land right-aligned (parsed as numbers, not text). Google Sheets
detects the dialect automatically.

If you open one of these in a `,`-delimited tool and everything lands in one column,
that is expected — it is not a bug.

---

## Columns per screen

Headers and their order mirror the on-screen table.

**Sujetos** — `Nombre` · `Documento` · `Fecha de nacimiento` · `Último relevamiento`
A subject who has never been measured is still exported, with `Último relevamiento` blank.

**Establecimientos** — `Nombre` · `Dirección` · `Ciudad` · `Provincia`

**Mediciones** — `Peso (kg)` · `Talla (cm)` · `IMC` · `Fecha` · `Sujeto` · `Comedor` ·
`Responsable` · `Alertas`
`Alertas` joins multiple alerts into one cell, comma-separated, in Spanish
(`Obesidad, Bajo peso`). Empty when the measurement raised none.

**Encuestas** — `Nombre` · `Alcance` · `Estado` · `Cantidad de preguntas` ·
`Fecha de creación`
`Alcance` is `Sujeto` / `Establecimiento` / `Anónima`. `Estado` is `Activa` / `Inactiva`.

**Detalle de Establecimiento** — `Nombre` · `Documento` · `Edad` ·
`Último relevamiento` · `Peso (kg)` · `Talla (cm)` · `IMC` · `Estado`
`Edad` renders as `5a 3m`. `Estado` is the nutritional status in Spanish
(`Normal`, `Sobrepeso`, `Obesidad`, `Emaciación`, `Emaciación severa`, `Bajo peso`,
`Bajo peso severo`).

> ⚠️ If any of these headers or their order does not match what the table renders,
> say so — the backend column specs live in one file
> (`app/services/exporters/csv/columns.py`) and are a one-line change each.
