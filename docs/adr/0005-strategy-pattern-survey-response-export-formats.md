# ADR-0005: Strategy pattern for survey response export formats

- **Status**: Accepted
- **Date**: 2026-07-26
- **Deciders**: Backend team
- **Related**: --

## Context

We require exporting a survey's responses at one establishment into a downloadable
file that includes both the raw response data and a visual summary of the
corresponding indicators (response count, last relevamiento date, and — for FIES
surveys — the score distribution). The initial implementation targets Excel (`.xlsx`
via `openpyxl`), but the requirement anticipates additional formats being needed
later (a PDF report was raised explicitly during design), and possibly
format-specific variants beyond a single alternate format.

A single `SurveyResponseService.export_to_xlsx()` method, with an
`if format == "pdf": ...` branch added inline for each new format, would keep
authorization, data retrieval, and file-layout logic in the same method. Every new
format would grow that branching, mix business rules (who can export, what data
qualifies) with presentation concerns (sheet layout, chart type, page styling), and
force any test of the XLSX layout to also exercise the full
authorization/retrieval path.

The formats considered don't share an implementation — only a contract: given a
survey and its already-authorized, already-fetched responses, produce a file's raw
bytes, plus the `content_type`/`file_extension` the HTTP layer needs to build the
response. This is the same shape of problem the codebase already solves elsewhere
with dependency injection via FastAPI's `Depends` (e.g.
`get_survey_response_service`) — a caller-selected implementation behind a stable
interface — applied here to a synchronous, non-request-scoped strategy instead of a
request-scoped service.

## Decision

**Export formats are implemented as interchangeable strategies behind a shared
interface, selected at request time via a factory — not as branches inside
`SurveyResponseService`.**

- `SurveyResponseExporter` (`app/services/exporters/base.py`): an abstract interface
  with `content_type`, `file_extension`, and
  `export(survey: SurveyDomain, responses: list[SurveyResponseDetailDomain]) -> bytes`.
  It receives only domain objects — no ORM types, no DB session — so an exporter
  cannot accidentally perform its own queries or bypass authorization.
- `XlsxSurveyResponseExporter` (`app/services/exporters/xlsx_exporter.py`): the first,
  and currently only, concrete implementation. Owns every XLSX-specific detail (sheet
  layout, native Excel chart for the FIES score distribution) with no leakage into
  the service or router.
- `get_exporter(format: ExportFormat) -> SurveyResponseExporter`
  (`app/services/exporters/factory.py`): a single lookup function mapping an
  `ExportFormat` enum value to its exporter class and instantiating it. This is the
  **only** place that knows the full set of supported formats.
- `SurveyResponseService.export()` depends solely on the `SurveyResponseExporter`
  interface. It performs authorization (`_DASHBOARD_ROLES`), resolves the survey,
  fetches every matching response via a dedicated non-paginated repository method
  (`list_all_for_export` — export needs the complete result set for one
  survey+establishment, not one page), converts them to
  `SurveyResponseDetailDomain` (the same shape already built for CA3's response
  detail view — no new data-shaping logic needed), and delegates file construction
  to whichever exporter the router injected.
- The router (`GET /survey-responses/export`) reads `format` as a query parameter
  (defaulting to `ExportFormat.XLSX`), resolves it through `get_exporter`, and wraps
  the returned bytes in a `Response` with the exporter's own `content_type` and a
  `Content-Disposition` header built from its `file_extension`.

## Consequences

**Positive**

- Adding a new format touches no existing code: a new class implementing
  `SurveyResponseExporter`, one new `ExportFormat` member, and one new entry in
  `factory.py`'s mapping. `SurveyResponseService.export()`, the router, and every
  existing exporter (including their tests) are unmodified — the same
  open/closed-principle guarantee the codebase already relies on for pluggable
  authorization roles (`require_some(*roles)`) and repository-backed services.
- Format-specific logic is unit-testable in complete isolation from HTTP,
  authorization, and the database: an exporter test builds `SurveyDomain` and
  `SurveyResponseDetailDomain` objects directly and asserts on the returned bytes
  (e.g. loading the `.xlsx` back with `openpyxl.load_workbook` and checking sheet
  names, row counts, and chart presence), with no `client`/`db_establishment`/
  `admin_user` fixtures involved.
- Clean separation between "what data is exported" (service: authorization,
  filtering, retrieval) and "how it's laid out" (exporter: sheet/page structure,
  charting). A styling change to the FIES score chart cannot accidentally affect who
  is allowed to export or which responses are included, and vice versa.
- Exporters consume the same `SurveyResponseDetailDomain` already produced for CA3
  (question text, resolved option labels, FIES score per response) — export required
  no new response-shaping code, only a new non-paginated repository query
  (`list_all_for_export`) to avoid CA3's per-row `get_with_relations` N+1 pattern when
  fetching an entire establishment's response set at once.

**Negative**

- Introduces an interface + factory for what is, at ship time, a single
  implementation. For a one-format system this indirection (router → factory →
  exporter) is arguably premature relative to a single method, and a reader has one
  more hop to follow than with inline branching.
- The shared `export(survey, responses) -> bytes` contract assumes every format can
  be built synchronously, fully in memory, from exactly those two inputs. A future
  format with materially different needs — a multi-step generation pipeline, calls to
  an external rendering service, or streamed rather than fully-buffered output —
  would strain this interface and likely require revisiting it rather than simply
  adding an implementation.
- `ExportFormat` and `_EXPORTERS` must be kept in sync by hand (an enum member with no
  matching factory entry raises `KeyError` at request time, not at import time or in
  a type check) — there is no compile-time guarantee the two stay aligned.

## Alternatives considered

**Single service method with format branching (`if format == "xlsx": ... elif
format == "pdf": ...`)** — the default "just add a branch" approach. Rejected because
it couples `SurveyResponseService` — which should only own authorization and data
retrieval — to every format's presentation details, and makes format-specific logic
untestable without exercising the full service call path.

**A format-agnostic "report data" DTO returned by the service, with formatting done
entirely in the router** — considered so the service wouldn't depend on any exporter
type at all. Rejected because it pushes the `export()` call (and thus the choice of
*which* exporter to invoke) into the router, splitting a single business operation
("export these responses") across two layers, and because the router has no natural
place to perform the authorization check that must gate the export.