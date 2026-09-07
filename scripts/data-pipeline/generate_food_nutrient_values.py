"""Generate food_nutrient_values.csv from raw/ and reference_data/{foods,nutrients}.csv.

One row per (food, nutrient) reading SARA 2 actually reports. A blank `valor_raw`
cell in raw/ means "not measured" (per ADR-0012) and is skipped entirely rather
than written as 0.

Foods excluded from the catalog at curation time (e.g. "Leche materna", see
generate_foods_draft.py's EXCLUDED_NAMES) are dropped the same way: their name
simply won't be in foods.csv, so their raw/ rows are skipped rather than
hardcoding the exclusion list a second time here.
"""

import csv
from pathlib import Path

BASE = Path(__file__).parent
REFERENCE_DATA = BASE.parent.parent / "app" / "reference_data"
RAW = BASE / "raw"
FOODS = REFERENCE_DATA / "foods.csv"
NUTRIENTS = REFERENCE_DATA / "nutrients.csv"
OUTPUT = REFERENCE_DATA / "food_nutrient_values.csv"

EXCLUDE_RAW_FILES = {
    "_blank_values.csv",
    "_nutrient_normalization_map.csv",
    "_review_irregulares.csv",
}


def main() -> None:
    with open(FOODS, newline="", encoding="utf-8") as f:
        name_to_food_code = {row["name"]: row["code"] for row in csv.DictReader(f)}

    with open(NUTRIENTS, newline="", encoding="utf-8") as f:
        name_to_nutrient_code = {row["name"]: row["code"] for row in csv.DictReader(f)}

    rows = []
    seen_pairs = set()
    skipped_names = set()
    skipped_blank = 0

    for path in sorted(RAW.iterdir()):
        if path.name in EXCLUDE_RAW_FILES or not path.name.endswith(".csv"):
            continue
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                name = row["alimento"]
                food_code = name_to_food_code.get(name)
                if food_code is None:
                    skipped_names.add(name)
                    continue

                value = row["valor_raw"].strip()
                if value == "":
                    skipped_blank += 1
                    continue

                nutrient_code = name_to_nutrient_code[row["nutriente"]]
                pair = (food_code, nutrient_code)
                if pair in seen_pairs:
                    raise ValueError(f"duplicate (food, nutrient) pair: {pair}")
                seen_pairs.add(pair)

                rows.append(
                    {
                        "food_code": food_code,
                        "nutrient_code": nutrient_code,
                        "amount_per_100g": value.replace(",", "."),
                    }
                )

    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["food_code", "nutrient_code", "amount_per_100g"]
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUTPUT}")
    print(f"Skipped {skipped_blank} blank cells (not measured)")
    print(f"Skipped names not in foods.csv (curated-out): {sorted(skipped_names)}")


if __name__ == "__main__":
    main()
