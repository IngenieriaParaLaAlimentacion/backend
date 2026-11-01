# CSV exports: client guide

## Context

Six listings can be downloaded as CSV: Subjects, Establishments, Measurements, Surveys, the
subjects of an Establishment and the stock of an Establishment. The export always reflects
what the user is looking at: same filters, same sort order, every matching row rather than
the current page.

Access follows the listing, except that exports are stricter:

- Five exports are restricted to roles **admin / analyst / superadmin**. A `field_worker`
  token receives `403`. Note this is stricter than two of the listings: `GET /establishments`
  is public and `GET /subjects` allows any role, but their exports are not.
- The stock export follows its listing: any authenticated role with access to the
  establishment. A field worker needs an approved link to it.

Missing or invalid token: `401`.

Base path: `/api/v1`.

The contract of each route (parameters and error codes) is in the Swagger UI at `/docs`. The
shared conventions are in [`api.md`](api.md#file-exports) and the design in
[ADR-0009](adr/0009-generic-csv-exporter-for-listings.md).

---

## The six endpoints

| Screen | Endpoint | Query params | Filename |
|---|---|---|---|
| Subjects | `GET /subjects/export` | same as `GET /subjects` | `sujetos_2026-08-24.csv` |
| Establishments | `GET /establishments/export` | same as `GET /establishments` | `establecimientos_2026-08-24.csv` |
| Measurements | `GET /measurements/export` | same as `GET /measurements` | `mediciones_2026-08-24.csv` |
| Surveys | `GET /surveys/export` | same as `GET /surveys` | `encuestas_2026-08-24.csv` |
| Establishment detail (attending subjects) | `GET /establishments/{establishment_id}/subjects/export` | same as `GET /establishments/{establishment_id}/subjects` | `sujetos_comedor-la-union_2026-08-24.csv` |
| Establishment stock | `GET /establishments/{establishment_id}/stock/export` | `category_id`, `only_available`, `sort_order`, as in the stock listing | `stock_comedor-la-union_2026-08-24.csv` |

**Send the same query string you sent the listing.** `page` and `page_size` have no effect:
an export returns every matching row. There is no separate "export filters" contract to
build.

`GET /subjects/export` and `GET /measurements/export` return `400` on an inverted range,
exactly like their listings (`birth_date_from > birth_date_to`, `min_age > max_age`,
`measured_from > measured_to`). The two establishment exports return `404` for an unknown
establishment, and the stock export returns `403` when the user has no access to it.

> Survey responses (`GET /surveys/{survey_id}/responses/export`) are a different export:
> an `.xlsx` file built in memory, not streamed, with its own `format` parameter. It does not
> follow this guide. See [ADR-0005](adr/0005-strategy-pattern-survey-response-export-formats.md).

---

## Response

```
HTTP/1.1 200 OK
Content-Type: text/csv; charset=utf-8
Content-Disposition: attachment; filename="sujetos_2026-08-24.csv"
Transfer-Encoding: chunked
X-Export-Row-Count: 2

Nombre;Documento;Fecha de nacimiento;Edad;Último relevamiento;Tiempo desde el último relevamiento
Ana Alvarez;20000001;14/03/2015;11a 5m;14/03/2026 07:30;hace 5 meses
Beto Benitez;20000002;01/07/2016;10a 1m;01/04/2026 07:00;hace 4 meses
```

The body is a complete file, not a JSON envelope. **It is streamed**: there is no
`Content-Length`, and the file is generated as it is sent.

### Read the body, do not hand the URL to the browser

This is the one important thing on this page. Because the file is streamed, the `200 OK` and
the headers go out **before** the server knows whether the query will finish. If it fails
midway, the server **drops the connection** (it does not send the final chunk), and the
client sees that as a network error *only if it is reading the body*.

```js
try {
  const res = await fetch(`/api/v1/subjects/export?${params}`, { headers });

  // Predictable errors (400/403/404) arrive before the first byte,
  // with a complete problem+json body.
  if (!res.ok) throw new Error((await res.json()).detail);

  const expected = Number(res.headers.get("X-Export-Row-Count"));
  const blob = await res.blob();          // <- rejects if the stream was cut

  // Extra check: rows received vs. rows the server declared.
  const text = await blob.text();
  const rows = text.trim().split("\r\n").length - 1;   // -1 for the header
  if (rows !== expected) throw new Error(`Expected ${expected} rows, got ${rows}`);

  const url = URL.createObjectURL(blob);
  Object.assign(document.createElement("a"), { href: url, download: filename }).click();
  URL.revokeObjectURL(url);
} catch (e) {
  showError("The export was interrupted. Try again.");
}
```

**An `<a href="/api/v1/subjects/export">`, or streaming straight to disk, would keep the
partial file without any warning.** That is the case to avoid.

`X-Export-Row-Count` states how many data rows to expect. No cell can contain a line break
(the backend normalizes them), so counting lines is valid. It also lets you show progress or
an "exporting N records…" message.

Prefer the server's filename, taken from `Content-Disposition`: it already carries the
entity, the date and, in the establishment exports, the establishment slug.

> If the app is ever served from a different origin than the API, reading
> `Content-Disposition` and `X-Export-Row-Count` from JavaScript requires the backend to send
> `Access-Control-Expose-Headers`. The API has no CORS middleware today, so clients are
> same-origin or behind a proxy and this does not apply. Tell the backend team if that changes.

---

## Empty results

A filter matching nothing returns **`200` with only the header line**: a valid, openable file
with zero data rows. The backend does not error on this.

Drive the button state from the listing you already have: **disable "Exportar CSV" when the
listing response's `total` is `0`**, and show the "no hay datos para exportar" message there.
Do not call the export endpoint to find out whether there is data.

---

## CSV format (read this before testing in Excel)

The file is tuned for **Excel in a Spanish locale**, which is how coordinators open it. Column
headers and enum labels are in Spanish.

| Aspect | Value | Why |
|---|---|---|
| Delimiter | `;` | Excel es-AR splits on `;`, not `,` |
| Decimals | comma, as in `18,52` | Matches the locale; unambiguous because the delimiter is `;` |
| Dates | `14/03/2015` | `dd/mm/aaaa` |
| Timestamps | `14/03/2026 07:30` | Converted to `America/Argentina/Buenos_Aires`. The API's JSON is UTC; **the CSV is not** |
| Encoding | UTF-8 **with BOM** | Without it Excel mangles `Ñ`, `ó`, `ú` |
| Line endings | CRLF | RFC 4180 |

Opening the file by double-clicking in Excel es-AR should need no import wizard, and numeric
columns should land right-aligned (parsed as numbers, not text). Google Sheets detects the
dialect automatically.

If you open one of these in a `,`-delimited tool and everything lands in one column, that is
expected, not a bug.

---

## Columns per screen

Headers and their order mirror the on-screen table. The backend column specs live in one file,
`app/services/exporters/csv/columns.py`.

**Subjects**: `Nombre` · `Documento` · `Fecha de nacimiento` · `Edad` ·
`Último relevamiento` · `Tiempo desde el último relevamiento`

`Edad` is the current age in completed months, written as `18a 6m`, `2a 0m`, `0a 3m` or
`0a 0m`. The reference instant is captured once when the export begins, and its Argentina
calendar day is used for every row and the filename, even when streaming crosses midnight.
Future birth dates clamp to `0a 0m`.

The elapsed time uses Argentina calendar days and completed months: `hoy` on the same day,
`hace N días` before one full month, `hace N meses` before twelve full months, and
`hace N años` after that, with singular forms for one. A missing measurement, or one dated
after the reference day, leaves the cell blank. A subject who has never been measured is still
exported, with both `Último relevamiento` and the elapsed time blank.

**Establishments**: `Nombre` · `Dirección` · `Ciudad` · `Provincia`

**Measurements**: `Peso (kg)` · `Talla (cm)` · `IMC` · `Fecha` · `Sujeto` · `Comedor` ·
`Responsable` · `Alertas` · `Observación`

`Alertas` joins multiple alerts into one cell, comma-separated, in Spanish
(`Obesidad, Bajo peso`). It is empty when the measurement raised none.

**Surveys**: `Nombre` · `Alcance` · `Estado` · `Cantidad de preguntas` · `Fecha de creación`

`Alcance` is `Sujeto`, `Establecimiento` or `Anónima`. `Estado` is `Activa` or `Inactiva`.

**Establishment detail**: `Nombre` · `Documento` · `Edad` · `Último relevamiento` ·
`Peso (kg)` · `Talla (cm)` · `IMC` · `Estado`

`Edad` is the age at the time of the subject's latest measurement here, written as `5a 3m`.
`Estado` is the nutritional status in Spanish: `Normal`, `Sobrepeso`, `Obesidad`,
`Emaciación`, `Emaciación severa`, `Bajo peso` or `Bajo peso severo`.

**Establishment stock**: `Alimento` · `Categoría` · `Cantidad` · `Unidad` ·
`Última actualización`

`Cantidad` is written with three decimals.

> If any of these headers or their order does not match what the table renders, say so. Each
> column is a one-line change in `columns.py`.
