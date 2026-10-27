# ADR-0027: Monthly nutrition report and its PDF

- **Status**: Accepted
- **Date**: 2026-10-27
- **Deciders**: Backend team
- **Related**: Issue #171 (monthly nutrition report), ADR-0021, ADR-0024, ADR-0025

## Context

Admins and analysts need, for each establishment and calendar month, a report of how well the food that arrived covers the nutrients of the children it feeds, with a Spanish write-up they can read and a PDF they can hand over.

Three things pull in different directions:

- The figures must be exactly reproducible and auditable, while the write-up is prose that only a language model can produce.
- A month's report is requested again and again (by several users, from a list, as a PDF), and each AI call costs money and quota.
- The AI can fail, and the PDF needs a library that the container image does not have today.

## Decision

### The backend calculates, the AI only writes

The analysis comes from the nutrition engine (ADR-0021, ADR-0025): per-nutrient adequacy against the reference per 1,000 kcal, macronutrient shares, GAPA group shares, suggested foods and the foods left out for lacking a gram conversion. The AI receives these figures and writes a Spanish summary. It never calculates or adds numbers, and its answer is validated against a fixed schema (Pydantic enforces the lengths; the schema sent to the provider has no bounds, because strict structured output rejects them).

A fixed `scope_note` states what the report does and does not assess. It is part of the response and is not written by the AI, so it cannot be dropped or reworded by a model.

### A report is a snapshot

A generated report is stored as a JSONB snapshot of the analysis, with the AI's summary exactly as written and a `summary_status`: `generated`, `unavailable` (the AI failed) or `not_applicable` (a month without intakes, which never calls the AI). It also keeps each nutrient's reference and minimum, so the figures stay readable if the reference data changes later. The prompt version is logged, not stored.

Intakes loaded afterwards for a month that already has a report do not change it, and there is no regeneration. A report is a statement of what was known when it was generated.

### Generating is idempotent and serialized

`PUT /establishments/{id}/nutrition-reports/{month}` returns the saved report (200), or generates and saves it (201). A transaction-level advisory lock per establishment and month is taken before looking the report up, so concurrent requests for the same month wait and then find the saved report instead of calling the AI twice.

If the AI fails, the calculated data is saved with the summary `unavailable`, and the next `PUT` of that month writes only the summary again.

Every `PUT` counts toward the per-user AI quota, even when it returns a saved report. Listing, reading and downloading the PDF do not.

The whole `PUT` is bounded by its own time budget, like recipes and receipts. When it runs out, the request answers 504 and nothing is saved. The report uses its own AI models (`OPENROUTER_REPORT_MODELS`), passed per call to the shared client.

### The PDF is rendered from saved data, with WeasyPrint

`GET .../nutrition-reports/{month}/pdf` renders a saved report: it never generates one and never calls the AI.

- A month with no saved report answers 404.
- A report whose summary is `unavailable` answers 409 with an error that asks to request the report again. A PDF without its text would look complete and is not.
- A month without intakes is delivered as a short PDF without the scope note, because there is nothing to qualify.

The PDF is built from Jinja2 HTML and CSS templates (`app/templates/reports/`) in the same palette as the emails, converted by WeasyPrint. The render is CPU-bound, so it runs in a worker thread after the database connection is released. WeasyPrint is imported only when a PDF is requested, so the application starts on a machine without its native libraries. Its URL fetcher accepts only `data:` URIs, so a template can never reach a file or the network.

Display names and units (nutrients, limits, macros, GAPA groups) live in `app/domain/nutrition_report.py`, as pure data checked against the nutrient catalog by tests.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Compute the figures with the AI | Not reproducible or auditable, and a wrong number would look authoritative |
| Regenerate the report when intakes change | Two reads of the same month would disagree, each regeneration costs AI quota, and users lose what they already read |
| Store only the AI text and recalculate the figures on read | A change in references or conversions would silently rewrite old reports |
| PDF without a text when the AI failed | Looks complete while missing its main section |
| `wkhtmltopdf` | The project is archived |
| Headless Chromium | Heavy to ship and run for a static page |
| `xhtml2pdf` | Limited CSS support, so the layout would be hard to maintain |
| `reportlab` | Defensible, but the layout is code instead of a template; WeasyPrint reuses the HTML/CSS and Jinja2 approach already used for the emails |

## Consequences

- The Docker image and the CI setup install Pango, HarfBuzz and the DejaVu fonts (about 20 MB). Only DejaVu fonts exist in the image, so the stylesheet falls back to them after the brand fonts.
- A deployment must set `OPENROUTER_REPORT_MODELS`. With it empty, no report gets its AI text (`unavailable`) and no PDF can be downloaded until it is configured.
- The quality of the write-up depends on the model. The prompt is versioned (`v2`) and the output is validated, but its wording is not guaranteed.
- A report cannot be refreshed after new intakes arrive. If that becomes a need, it is a new feature that decides which version of a month is the current one.
