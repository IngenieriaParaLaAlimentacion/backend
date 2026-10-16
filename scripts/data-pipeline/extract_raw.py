"""Stage 1 — raw, uninterpreted extraction of the SARA 2 food-composition tables.

This is a one-off tool script, not part of the app runtime. It does not filter,
categorize, or curate anything: it only (a) reads the PDF's table grids via
pdfplumber, (b) un-mirrors text that the PDF renders rotated 180 degrees, and
(c) reshapes each page's "nutrients as rows / foods as columns" grid into a
long-format (one row per food+nutrient reading) table, which is the minimal
reshape needed to have a human-checkable notion of "row".

Known raw-extraction artifact (left AS-IS, not fixed here — flagged for the
Stage 2 cleaning criteria): on macronutrient-table pages, pdfplumber's cell
boundary detection sometimes glues the "Carbohidratos disponibles" label
together with the "Ácidos grasos" sub-list of labels that follows it (no
ruling line separates them in the PDF). The numeric data for every row is
still captured correctly and independently; only that one label cell's text
is polluted with extra content. See the report given after running this
script.
"""

import csv
import re
import unicodedata
from pathlib import Path

import pdfplumber

PDF_PATH = Path(__file__).parent / "sara2.pdf"
OUT_DIR = Path(__file__).parent / "raw"

GROUP_NAMES = {
    1: "Verduras",
    2: "Frutas",
    3: "Legumbres, cereales, papa, choclo, batata, pan y pastas",
    4: "Leche y postres de leche",
    5: "Yogures",
    6: "Quesos",
    7: "Carnes",
    8: "Huevos",
    9: "Pescados y mariscos",
    10: "Aceites",
    11: "Frutas secas y semillas",
    12: "Azúcares, mermeladas y dulces",
    13: "Golosinas y chocolates",
    14: "Grasas",
    15: "Snacks salados",
    16: "Aderezos",
    17: "Caldos y sopas industriales",
    18: "Postres industriales y helados",
    19: "Sales",
    20: "Bebidas con azúcar",
    21: "Bebidas sin azúcar",
    22: "Bebidas alcohólicas y energizantes",
    23: "Bebidas de frutas naturales o mínimamente procesadas sin azúcar agregada",
    24: "Infusiones",
    25: "Alimentos de locales de comidas rápidas",
    26: "Suplementos nutricionales",
}

TABLE_LETTER_NAME = {
    "A": "macronutrientes",
    "B": "vitaminas_minerales",
}

KNOWN_UNITS = {"g", "mg", "µg", "kcal"}

MARKER_RE = re.compile(r"^:([AB])\.?(\d{1,2})(\s|$)")

# Nutrient labels that only ever appear on one of the two table types — used to
# determine the actual table type from its extracted content rather than from
# page title text. The title-text approach previously used a raw substring
# search for "vitaminas"/"macronutrientes" over the first 2000 characters of
# page text, which false-positived whenever a food name on a macronutrient page
# happened to contain the word "vitaminas" (e.g. "Leche ... fortificada con
# vitaminas A y D"), mislabeling 16 of 122 pages across 10 groups.
MACRO_ONLY_LABEL = "Agua"
VITAMIN_ONLY_LABEL = "Calcio"


def determine_table_letter(labels: set[str]) -> str | None:
    if VITAMIN_ONLY_LABEL in labels:
        return "B"
    if MACRO_ONLY_LABEL in labels:
        return "A"
    return None


# Known raw-extraction artifact (left AS-IS, not fixed here — flagged for the
# Stage 2 cleaning criteria): the source PDF's font renders "fi" as a single
# ligature glyph in some words but not others (confirmed against the PDF
# itself — on page 37, pdfplumber's raw extracted word for "fortificados" is
# "sodacfiitrof", not the "sodacifitrof" a clean 180-degree mirroring would
# produce: the "fi" pair keeps its f-then-i order instead of flipping with
# everything else). A blanket fix that treats every "fi"/"fl" substring as a
# ligature is unsafe — it corrupts the (more common) case of a word that
# legitimately contains "if", like "Coliflor" or "Alfa", where the plain
# reversal is already correct. Since raw text alone can't tell the two cases
# apart, this is left for manual, per-word correction in Stage 2 rather than
# a heuristic here.
def fix_mirrored(s: str | None) -> str | None:
    """Undo the PDF's 180-degree-rotated text rendering for
    a label/unit/food-name cell."""
    if not s:
        return s
    return s[::-1].replace("\n", " ").strip()


def slugify(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_only = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return ascii_only


def compact_reversed(name: str) -> str:
    return re.sub(r"\s+", "", name)[::-1].lower()


COMPACT_REVERSED_GROUP_NAMES = {
    n: compact_reversed(name) for n, name in GROUP_NAMES.items()
}


def detect_group_from_title(compact_raw: str) -> int | None:
    """Find which group name (reversed, whitespace-stripped) appears in this page's
    text. Used to cross-check / override the numeric marker, which we've found to
    sometimes be wrong in the source PDF itself (see report)."""
    # Exact match first: some group names are substrings of others (e.g. "Frutas"
    # inside "Bebidas de frutas naturales..."), so only fall back to substring
    # matching when nothing matches exactly.
    for n, needle in COMPACT_REVERSED_GROUP_NAMES.items():
        if needle == compact_raw:
            return n
    matches = [
        n for n, needle in COMPACT_REVERSED_GROUP_NAMES.items() if needle in compact_raw
    ]
    if not matches:
        return None
    return max(matches, key=lambda n: len(GROUP_NAMES[n]))


def detect_marker(page) -> tuple[str, int] | None:
    # The whole line is mirrored (180-degree rotated text), so the digits of the
    # group number are also reversed (e.g. group 19 appears as ":A.91") — reverse
    # the captured digit string back before parsing it as an int. Group 5's pages
    # additionally use a "5A"/"5B" format (no dot) rather than "5.A"/"5.B".
    text = page.extract_text() or ""
    lines = text.split("\n")

    marker_letter = None
    marker_group_num = None
    marker_line_idx = None
    for i, line in enumerate(lines):
        m = MARKER_RE.match(line.strip())
        if m:
            marker_letter = m.group(1)
            marker_group_num = int(m.group(2)[::-1])
            marker_line_idx = i
            break
    if marker_group_num is None:
        return None

    # Only search the title block (the few lines right before the marker line) for
    # a group-name match, not the whole page — the food-item names further down the
    # page can themselves contain words like "queso"/"huevo"/"grasa" as ingredients
    # of a composite dish, which caused false-positive group matches when the whole
    # page was searched.
    title_block = "\n".join(lines[max(0, marker_line_idx - 20) : marker_line_idx])
    compact_title = re.sub(r"\s+", "", title_block).lower()

    title_group_num = detect_group_from_title(compact_title)
    group_num = marker_group_num
    if title_group_num is not None and title_group_num != marker_group_num:
        print(
            f"  [FIXUP] marker said group {marker_group_num} but title text matches "
            f"group {title_group_num} ({GROUP_NAMES[title_group_num]}) — using title"
        )
        group_num = title_group_num

    # table_letter here is only the initial guess from the marker regex — it is
    # known unreliable (group 5's pages print "5A" even on its vitamin/mineral
    # table) and gets overridden in extract_page() by the actual nutrient labels
    # found on the page, which is a more reliable signal.
    return marker_letter, group_num


def find_value_start_index(rows: list[list[str | None]]) -> int | None:
    """Find the column index where numeric food-value columns begin, by locating
    the first cell (scanning row by row) whose un-mirrored text is a known unit."""
    for row in rows:
        for idx, cell in enumerate(row):
            if cell and fix_mirrored(cell).lower() in KNOWN_UNITS:
                return idx + 1
    return None


def extract_page(page, group_num: int, table_letter: str, page_idx: int) -> list[dict]:
    table = page.extract_table()
    if not table:
        return []

    value_start = find_value_start_index(table)
    if value_start is None:
        print(f"  [WARN] page {page_idx}: no unit column found, skipping page")
        return []

    header_row = None
    data_rows = []
    for row in table:
        label_cells = [c for c in row[:value_start] if c]
        if len(label_cells) >= 3 and fix_mirrored(label_cells[0]) == "Ácidos grasos":
            # The "Ácidos grasos" section-header row is glued to the data row of
            # the first fatty acid that follows it (always 22:6 DHA — confirmed
            # identical across every macro-nutrient page checked, no ruling line
            # separates them in the PDF). The real label is the second cell; the
            # header text in the first cell is not a nutrient and is dropped.
            # Its values are otherwise captured correctly and independently.
            label = fix_mirrored(label_cells[1])
        else:
            label = fix_mirrored(label_cells[0]) if label_cells else None
        if label and label.lower() == "alimento":
            header_row = row
        else:
            data_rows.append((label, row))

    if header_row is None:
        print(
            f"  [WARN] page {page_idx}: no 'Alimento' header row found, skipping page"
        )
        return []

    labels_present = {label for label, _ in data_rows if label}
    detected_letter = determine_table_letter(labels_present)
    if detected_letter is None:
        print(
            f"  [WARN] page {page_idx}: couldn't determine table type from nutrient "
            f"labels, trusting marker ({TABLE_LETTER_NAME[table_letter]})"
        )
    elif detected_letter != table_letter:
        print(
            f"  [FIXUP] page {page_idx}: marker said tabla "
            f"{TABLE_LETTER_NAME[table_letter]} but nutrient labels "
            f"match {TABLE_LETTER_NAME[detected_letter]} — using content"
        )
        table_letter = detected_letter
    else:
        table_letter = detected_letter

    print(
        f"page {page_idx}: grupo {group_num} ({GROUP_NAMES[group_num]}) "
        f"- tabla {table_letter}"
    )

    food_names = [fix_mirrored(c) for c in header_row[value_start:]]

    out_rows = []
    for label, row in data_rows:
        if not label:
            continue
        values = row[value_start:]
        for food_name, value in zip(food_names, values):
            if food_name is None:
                continue
            # Value cells are mirrored the same as label cells (confirmed against
            # the source: e.g. pure sunflower oil's raw energy value extracts as
            # "009", which is "900 kcal" — the textbook value for pure fat —
            # reversed). Unlike labels, values never wrap across multiple lines,
            # so a plain reversal is enough; no newline-joining needed.
            value = value[::-1] if value else value
            out_rows.append(
                {
                    "grupo_num": group_num,
                    "grupo_nombre": GROUP_NAMES[group_num],
                    "tabla": TABLE_LETTER_NAME[table_letter],
                    "pagina_pdf": page_idx,
                    "alimento": food_name,
                    "nutriente": label,
                    "valor_raw": value,
                }
            )
    return out_rows


def main():
    OUT_DIR.mkdir(exist_ok=True)
    rows_by_group: dict[int, list[dict]] = {n: [] for n in GROUP_NAMES}
    pages_processed = 0
    pages_skipped_no_marker = 0

    with pdfplumber.open(PDF_PATH) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            if page_idx < 17:
                continue
            marker = detect_marker(page)
            if marker is None:
                pages_skipped_no_marker += 1
                print(f"  [SKIP] page {page_idx}: no A/B marker found")
                continue
            table_letter, group_num = marker
            if group_num not in GROUP_NAMES:
                print(f"  [WARN] page {page_idx}: unknown group number {group_num}")
                continue
            out_rows = extract_page(page, group_num, table_letter, page_idx)
            rows_by_group[group_num].extend(out_rows)
            pages_processed += 1

    total_rows = 0
    fieldnames = [
        "grupo_num",
        "grupo_nombre",
        "tabla",
        "pagina_pdf",
        "alimento",
        "nutriente",
        "valor_raw",
    ]
    for group_num, rows in rows_by_group.items():
        if not rows:
            print(
                f"  [WARN] group {group_num} ({GROUP_NAMES[group_num]}):"
                f" 0 rows extracted"
            )
            continue
        slug = slugify(GROUP_NAMES[group_num])
        out_path = OUT_DIR / f"{group_num:02d}_{slug}.csv"
        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        total_rows += len(rows)
        print(f"  wrote {out_path} ({len(rows)} rows)")

    print()
    print(f"Pages processed: {pages_processed}")
    print(f"Pages skipped (no A/B marker): {pages_skipped_no_marker}")
    print(f"Total raw rows extracted: {total_rows}")


if __name__ == "__main__":
    main()
