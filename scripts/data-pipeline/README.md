# Food catalog data pipeline

One-off pipeline that turned the SARA 2 PDF into the food catalog seed data the
app actually loads: `app/reference_data/{food_categories,foods,nutrients,food_nutrient_values}.csv`,
consumed by `seed_food_catalog.py` at container boot.

Not part of the app runtime — excluded from the Docker build context
(`.dockerignore`). Kept in version control so the extraction is reproducible and
auditable, per ADR-0010.

For the design decisions behind the source, the seed mechanism, and the DB
schema, see `docs/adr/0010-food-catalog-source.md`, `0011-food-catalog-seed-and-upsert.md`
and `0012-food-catalog-relational-schema.md`. This file only covers the pipeline
itself, as it stands today.

## Layout

| Path | What it is |
|---|---|
| `requirements.txt` | Pinned `pdfplumber`/`pdfminer.six` versions. **Not optional**. |
| `extract_raw.py` | PDF → `raw/*.csv`. One row per (food, nutrient) reading, per SARA 2 group. |
| `raw/` | The extraction's output, **after manual review and correction** (see below) — this is the source of truth, not a regenerable cache. |
| `generate_foods_draft.py` | `raw/` + `app/reference_data/food_categories.csv` → the `foods` seed data (name, category, `base_unit`). |
| `generate_food_nutrient_values.py` | `raw/` + `app/reference_data/{foods,nutrients}.csv` → `app/reference_data/food_nutrient_values.csv`. |

The source PDF (SARA 2 — Tabla de Composición Química de Alimentos para
Argentina, Ministerio de Salud / CESNI, ENNyS 2) is **not** kept in this repo —
it's a public document, re-downloadable at need, and there's no reason to carry
a third-party PDF in version control when `raw/` already holds everything this
pipeline extracted from it. Save it as `sara2.pdf` in this directory before
running `extract_raw.py`.

## Reproducing a run

```bash
cd scripts/data-pipeline
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# place sara2.pdf here (see "Layout" above)
python extract_raw.py                     # PDF -> raw/*.csv
python generate_foods_draft.py             # raw/ -> foods_draft.csv (draft, not committed)
python generate_food_nutrient_values.py    # raw/ -> app/reference_data/food_nutrient_values.csv
```

`foods_draft.csv` is a working intermediate, not kept in the repo — review it,
then hand-copy the columns the schema actually uses (`code,name,category,base_unit,source_page`)
into `app/reference_data/foods.csv` (drop the audit-only `override_applied` column).

**`raw/` is not something to blindly regenerate.** Re-running `extract_raw.py`
reproduces the mechanical extraction, but a substantial number of entries in
`raw/` were corrected by hand afterwards — reconstructed word order, ligature
typos, table-crossover mismatches — verified letter-by-letter against the PDF
and applied directly to these CSVs, not all of it as code in `extract_raw.py`.
Re-running the script from scratch would silently lose those corrections. Treat
`raw/` itself as the checked-in source of truth for the catalog's text content;
only re-run `extract_raw.py` if you're starting a fresh extraction and are
prepared to redo that review.


## Known data quirks (intentional, don't "fix" these)

- **The "fi" ligature bug**: some words with the "fi" digraph decode with the
  two letters swapped (e.g. "fortificados" → "fortiifcados"), a PDF encoding
  quirk. Left uncorrected in `raw/` except where it happened to fall inside an
  already-verified name correction. There's no safe general fix — a blanket
  regex breaks unrelated words (e.g. "Coliflor").
- **`Salmón blanco, crudo` has no vitamins/minerals row.** Confirmed against
  the PDF itself: the table cell is genuinely empty (no text, no ruling
  missing), not an extraction gap. Left with only its macronutrient values.
- **`Salvado de avena`'s ALA fatty-acid value uses `.` as the decimal
  separator** (`0.121`) where the rest of the dataset uses `,`. Both formats
  parse unambiguously, so it was loaded as-is rather than silently "corrected"
  without being able to confirm intent against the source.
- **Blank cells in `raw/` mean "not measured," never `0`.** Downstream, this
  becomes an absent row in `food_nutrient_values`, not a zero value (see
  ADR-0012). `raw/_blank_values.csv` is the full audit list of these.
- **Groups 23 (bebidas de frutas naturales) and 26 (suplementos nutricionales)
  are excluded from the catalog entirely** — never extracted into `raw/` at
  all, not just filtered out downstream. **"Leche materna" is excluded
  individually**, at the curation stage (`generate_foods_draft.py`'s
  `EXCLUDED_NAMES`) rather than in `raw/`, since `raw/` stays a faithful
  extraction of the source. Neither is something an establishment receives as
  stock.