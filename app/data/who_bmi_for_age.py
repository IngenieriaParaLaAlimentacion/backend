"""
WHO BMI-for-age LMS reference tables.

Keys:   ("male" | "female", age_in_months: int)
Values: (L: float, M: float, S: float)

L — Box-Cox power (lambda)
M — Median
S — Coefficient of variation (sigma)

Z-score formula:  z = ((BMI / M) ** L - 1) / (L * S)
Special case L≈0: z = ln(BMI / M) / S

--- HOW TO POPULATE THIS FILE ---

1. Download the four official WHO CSV/Excel files:

   0–5 years, boys:
     https://www.who.int/childgrowth/standards/bmi_for_age/bfa_boys_0_5_zscores.xlsx

   0–5 years, girls:
     https://www.who.int/childgrowth/standards/bmi_for_age/bfa_girls_0_5_zscores.xlsx

   5–19 years, boys:
     https://www.who.int/growthref/bfa_boys_5_19years_zscores.xlsx

   5–19 years, girls:
     https://www.who.int/growthref/bfa_girls_5_19years_zscores.xlsx

2. Each file has columns: Month, L, M, S (plus SD columns you can ignore).
   Ages 0–60 for the 0–5 files; 61–228 for the 5–19 files.

3. Run the following one-off conversion (requires openpyxl):

   import openpyxl
   from pathlib import Path

   files = {
       "male":   ["bfa_boys_0_5_zscores.xlsx",  "bfa_boys_5_19years_zscores.xlsx"],
       "female": ["bfa_girls_0_5_zscores.xlsx", "bfa_girls_5_19years_zscores.xlsx"],
   }

   for sex, paths in files.items():
       for path in paths:
           ws = openpyxl.load_workbook(path).active
           for row in ws.iter_rows(min_row=2, values_only=True):
               month, l, m, s = int(row[0]), float(row[1]), float(row[2]), float(row[3])
               print(f'    ("{sex}", {month}): ({l}, {m}, {s}),')

4. Paste the output into WHO_BMI_LMS below, replacing the empty dict.
"""

# TODO: populate with official WHO LMS values (see instructions above).
WHO_BMI_LMS: dict[tuple[str, int], tuple[float, float, float]] = {}
