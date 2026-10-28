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
Transfer-Encoding: chunked
X-Export-Row-Count: 2

Nombre;Documento;Fecha de nacimiento;Edad;Último relevamiento;Tiempo desde el último relevamiento
Ana Alvarez;20000001;14/03/2015;11 a 5 m;14/03/2026 07:30;hace 5 meses
Beto Benitez;20000002;01/07/2016;10 a 1 m;01/04/2026 07:00;hace 4 meses
```

El body es un archivo completo, no un envelope JSON. **Se envía por streaming**: no hay
`Content-Length`, el archivo se genera a medida que se manda.

### ⚠️ Leé el body — no le pases la URL al browser

Esto es lo único importante de esta página. Como el archivo se streamea, el `200 OK` y los
headers salen **antes** de que el servidor sepa si la query va a terminar bien. Si falla a
mitad de camino, el servidor **corta la conexión** (no manda el chunk final), y eso el
cliente lo ve como un error de red *solo si está leyendo el body*.

```js
try {
  const res = await fetch(`/api/v1/subjects/export?${params}`, { headers });

  // Los errores previsibles (400/403/404) llegan antes del primer byte,
  // con problem+json completo.
  if (!res.ok) throw new Error((await res.json()).detail);

  const expected = Number(res.headers.get("X-Export-Row-Count"));
  const blob = await res.blob();          // <- rechaza si el stream se cortó

  // Chequeo extra: las filas que llegaron vs. las que el server declaró.
  const text = await blob.text();
  const rows = text.trim().split("\r\n").length - 1;   // -1 por el encabezado
  if (rows !== expected) throw new Error(`Esperaba ${expected} filas, llegaron ${rows}`);

  const url = URL.createObjectURL(blob);
  Object.assign(document.createElement("a"), { href: url, download: filename }).click();
  URL.revokeObjectURL(url);
} catch (e) {
  showError("La exportación se interrumpió. Volvé a intentar.");
}
```

**Un `<a href="/api/v1/subjects/export">` o un stream-a-disco directo se quedarían con el
archivo parcial sin avisar.** Ese es el caso a evitar.

`X-Export-Row-Count` dice cuántas filas de datos esperar. Ninguna celda puede contener un
salto de línea (el backend los normaliza), así que contar líneas es válido. También sirve
para mostrar progreso o un "exportando N registros…".

Preferí el nombre de archivo del servidor, sacado de `Content-Disposition`: ya trae la
entidad, la fecha y el slug del establecimiento en el export de detalle.

> Si algún día la app se sirve desde otro origen que la API, leer `Content-Disposition` y
> `X-Export-Row-Count` desde JS requiere que el backend mande
> `Access-Control-Expose-Headers`. Hoy la API no tiene CORS middleware, así que los
> clientes son same-origin/proxy y no aplica — avisá a backend si eso cambia.

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

**Sujetos** — `Nombre` · `Documento` · `Fecha de nacimiento` · `Edad` ·
`Último relevamiento` · `Tiempo desde el último relevamiento`

`Edad` is current age in completed months, formatted like the web's `formatAgeMonths`
(`18 a 6 m`, `2 a`, `3 m`, `0 m`). The reference instant is captured once when the
export begins; its Argentina calendar day is used for every row and the filename,
even when streaming crosses midnight. Future birth dates clamp to `0 m`.

Elapsed time uses Argentina calendar days and completed months: `hoy` on the same
day, `hace N días` before one full month, `hace N meses` before twelve full months,
and `hace N años` thereafter, with singular forms for one. Missing or future
measurement instants render `—` in the new elapsed column. A subject who has never
been measured is still exported, with `Último relevamiento` blank and elapsed `—`.
The existing timestamp retains its `DD/MM/YYYY HH:MM` format.

The two added fields intentionally expand the subject CSV from four to six columns;
positional CSV imports must account for the inserted age and appended elapsed value.
Establishment subjects keep their existing age-at-measurement column and format.

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
