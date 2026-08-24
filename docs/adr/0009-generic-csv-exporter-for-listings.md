# ADR-0009: Generic CSV exporter for the listing views

- **Status**: Accepted
- **Date**: 2026-08-24
- **Deciders**: Backend team
- **Related**: ADR-0005 (Strategy pattern for survey response export formats)

## Context

Five listing views — Sujetos, Establecimientos, Mediciones, Encuestas and the
per-establishment subject listing — needed a "Exportar CSV" action. The
requirement is that the file carries exactly the rows the user is looking at:
same filters, same sort order, no pagination window.

ADR-0005 already established a Strategy for exports, but its interface is
`export(survey: SurveyDomain, responses: list[SurveyResponseDetailDomain]) ->
bytes`. That contract is specific to one survey and its responses, and the one
implementation behind it also writes a summary sheet with a native Excel chart.
None of that transfers to a listing, which is plain tabular data: a sequence of
domain objects and an ordered set of columns.

Two options were on the table: add `ExportFormat.CSV` to the existing factory
and widen `SurveyResponseExporter`, or introduce a second exporter type for
tabular listings.

The listings themselves posed a separate problem. Each repository already owned
its filter conditions (`_listing_conditions`) and sort map (`_SORT_CLAUSES`),
but only behind a paginated method. An export needs the same filtering and
ordering without limit/offset, and any second implementation of that logic
would be free to drift from the listing it is supposed to mirror — which is the
one thing the acceptance criteria forbid.

## Decision

**Listing exports use a separate, generic, column-spec-driven `CsvExporter[T]`,
and every repository's export query is built from the same filter and sort
definitions as its paginated listing.**

- `CsvColumn[T]` (`app/services/exporters/csv/csv_exporter.py`): a frozen
  dataclass pairing a header string with a `Callable[[T], str]`. The header must
  match the UI table's column name, and a view's column order must match the
  table's.
- `CsvExporter[T]` (same module): binds one column spec plus an entity name, and
  exposes `content_type`, `file_extension`, `export(rows) -> bytes` and
  `filename(scope=None)`. `export` takes an `Iterable`, so services stream
  domain objects in rather than materialising a second list. The header row is
  always written, which is what makes an empty result set a valid file.
- `app/services/exporters/csv/columns.py` holds the five specs and one bound
  exporter instance each. All the Spanish header strings live in that one
  module, so their correspondence to the UI is reviewable at a glance.
- `app/services/exporters/csv/formatters.py` owns the es-AR value rendering and
  the enum → Spanish label maps.
- Each service gained one `export_*` method mirroring its listing method. It
  receives the exporter as a parameter and returns bytes, keeping the ADR-0005
  seam: the service depends on the exporter type, never on the column spec.
- Each repository gained `list_all_for_export(params)`, built from the *same*
  `_listing_conditions` and `_SORT_CLAUSES` the paginated method uses. Where the
  base query was non-trivial it was extracted into a shared private builder
  (`_listing_base_query`, `_subject_listing_query`) consumed by both.
- `execute_all` / `execute_all_rows` (`app/utils/db.py`) are the unpaginated
  counterparts of `execute_paginated` / `execute_paginated_rows`.
- The routers reuse the *existing* query dataclasses from `app/api/v1/params.py`
  unchanged. That is what guarantees filter/sort parity at the API contract
  level: there is literally one definition of "the filters this view accepts".

**CSV dialect: Argentine, Excel-first.** `;` delimiter, decimal comma
(`18,52`), dates `dd/mm/aaaa`, timestamps converted to `America/Argentina/
Buenos_Aires`, CRLF line endings, and a leading UTF-8 BOM. Together these make
the file open correctly on a double-click in Excel es-AR — no import wizard, no
mojibake on `Ñ`/`ó`, and numeric columns parsed as numbers. The `;` delimiter is
what makes a decimal comma unambiguous; the two choices are a package.

**Authorization.** All five endpoints require admin/analyst/superadmin. This
deliberately narrows two views: `GET /establishments` is public and
`GET /subjects` allows any authenticated role, but exporting a whole padrón is a
reporting action rather than a lookup.

**No row cap.** An export returns the complete filtered set.

## Consequences

**Positive**

- Adding a sixth exportable listing is additive: a column spec, a repository
  `list_all_for_export`, a service `export_*`, and a route. No existing exporter,
  service or test changes.
- Filter/sort drift between a listing and its export is structurally prevented,
  not merely tested for — they share the query dataclass, the conditions builder
  and the sort map. Adding a filter to a listing adds it to the export for free.
- `SurveyResponseExporter` and its xlsx implementation were not touched, so the
  survey-response export and its tests are unaffected.
- Column specs are unit-testable with no HTTP, no auth and no database: build a
  domain object, export it, assert the row.
- Extracting the shared query builders surfaced that the measurement,
  establishment and survey listings sorted with no `id` tiebreaker. Tiebreakers
  were added, which also fixes page-shuffling on ties in the existing listings.

**Negative**

- There are now two export abstractions in `app/services/exporters/`, and a
  reader has to know which applies. The split is by shape of input (one
  aggregate + its children vs. rows + columns), not by file format, which is a
  distinction the package layout only hints at.
- The es-AR dialect is hardcoded. A consumer wanting RFC-4180-plain CSV (a
  `pandas.read_csv` pipeline, say) cannot ask for one; that would need a dialect
  parameter threaded through `CsvExporter`.
- Generation is synchronous and fully buffered, inherited from ADR-0005's
  contract. With no row cap, an unfiltered `mediciones` export holds every
  matching row and the whole rendered file in memory at once. `export` accepting
  an `Iterable` keeps the door open for a streaming variant, but the current
  `-> bytes` return type would have to change. This is the item to revisit first
  once production volumes are known.
- `columns.py` imports five domain modules, making it a wide dependency hub. It
  is presentation-only and imported by routers rather than by domain code, so
  the direction of the dependency stays correct.

## Alternatives considered

**Add `ExportFormat.CSV` to the ADR-0005 factory and widen
`SurveyResponseExporter`** — the "reuse the existing pattern" option the user
story raised. Rejected because the interface would have to become generic over
its input to serve both a survey aggregate and five unrelated row types,
degenerating to `export(anything) -> bytes` and losing the type safety that
makes the column specs checkable. The two exporters share a concept, not a
contract.

**A `format=csv` query parameter on the existing listing endpoints** — no new
routes. Rejected because a single operation would return either a
`PaginatedResponse` JSON body or a file, which cannot be expressed as one
`response_model`, and because the pagination parameters are meaningless for an
export while being required for the listing.

**Return rows from the service and build the CSV in the router** — considered so
services would not depend on an exporter type. Rejected for the same reason
ADR-0005 rejected it: it splits one business operation across two layers.
