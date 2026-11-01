# ADR-0017: Trigram-similarity catalog matching for receipt-extracted food lines

- **Status**: Accepted
- **Date**: 2026-09-19
- **Updated**: 2026-10-23
- **Deciders**: Backend team
- **Related**: ADR-0015 (receipt photo storage — the propose/confirm flow this ADR extends), ADR-0012 (food
  catalog relational schema — the source of `foods.base_unit`), ADR-0025 (unit conversion — how a printed
  quantity reaches the food's base unit), ADR-0010 (SARA 2 as the catalog source)

## Context

`POST /food-intakes/from-photo` extracts a list of food lines from a receipt photo via an LLM call (Gemini).
Each proposed line comes back with a free-text `description` read off the receipt (e.g. `"Arroz 1kg"`), plus
the quantity and unit text printed on the line, if any (`raw_quantity`, `raw_unit_text`). Without a catalog
match, `ProposedFoodLine.food` is always `null`, forcing the user to search and pick the matching catalog
entry themselves for every single line, even when the receipt text is an unambiguous match for an existing
`foods` row (e.g. `"Arroz 1kg"` against the catalog entry `"Arroz"`), and to type every quantity by hand.

The food catalog (ADR-0010, ADR-0012) already has catalog-wide fuzzy search: `pg_trgm` is enabled
(`eb850f66c679`), `foods.name` has a trigram index (`4099691d9bcd`), and `FoodRepository` already orders
catalog listing results by `similarity()` when a user types a search term
([food_repository.py:39-49](../../app/repositories/food_catalog/food_repository.py#L39-L49)). That
machinery ranks a human-typed query; it has never been used to make an automated, unattended matching
decision.

This ADR settles how a raw receipt-line description gets turned into a catalog `food` reference, how
confident that match has to be before it's shown to the user as already resolved, and when the printed
quantity can be carried over to the matched line.

## Decision

### Trigram similarity against `foods.name`, not an LLM-side catalog lookup

Matching is done with a Postgres query via the existing `pg_trgm` extension — not by asking the LLM to pick
from the catalog during extraction. Two reasons:

1. **The catalog has hundreds of entries** (SARA 2's full raw/as-purchased list, ADR-0010). Passing the
   full catalog into every Gemini prompt to have the model select from it would meaningfully grow prompt
   size and cost per receipt, for a lookup Postgres already does natively and fast via the existing trigram
   index.
2. **Determinism and testability.** A SQL similarity query is a pure function of `(description, foods.name)`
   at query time — same inputs, same output, and it is trivially unit-testable against a real Postgres
   instance (Testcontainers, consistent with how this codebase tests everything else DB-dependent). An
   LLM-side selection would make matching behavior dependent on model version and prompt phrasing, on top of
   what the extraction step already depends on it for.

### Two configurable trigram scores, both required, decide auto-match vs. leaving `food` null

`FoodRepository.find_best_match(description, min_word_similarity, min_similarity)` returns the food with the
highest `word_similarity(unaccent(lower(foods.name)), unaccent(lower(description)))` among those where *both*
that score and `similarity(unaccent(lower(foods.name)), unaccent(lower(description)))` clear their respective
floor, or `None` if nothing clears both. There is no "top-N suggestions" list — this is a binary decision per
line: either the match is confident enough to prefill, or the line is left with `food=null`, and the user
searches manually.

Both thresholds are plain settings — not schema columns, not hardcoded in the query — tunable from real
receipt data without a migration or a deploy of new query code:

- `receipt_food_match_min_word_similarity` (default `0.5`): the primary signal. `word_similarity` scores a
  catalog name against its best-matching contiguous extent of the description, so it isn't diluted by a
  brand name or pack size elsewhere in the line. Whole-string `similarity()` is a Jaccard-like ratio over the
  *union* of both strings' trigrams, so a short catalog name compared against a long, noisy line scores low
  even when it is a perfect substring: `"Ketchup HELLMANNS x250g DOY 237 gr. (21,00)"` does not reach a
  usable `similarity()` against `"Ketchup"`. On real receipts this affected most lines, not just edge cases.
- `receipt_food_match_min_similarity` (default `0.22`): a whole-string `similarity` floor applied alongside
  it. `word_similarity` alone is a poor filter for *short* catalog names: against the full catalog
  (`app/reference_data/foods.csv`, ~900 rows), a name like `"Sal"` scores 0.5–0.75 against a coincidental
  extent of a completely unrelated line, sometimes above genuine matches. A genuine match also carries
  non-trivial whole-string overlap with the full description; a short spurious match doesn't. This floor
  exists specifically to reject that case.

Neither score alone gives a threshold that cleanly separates real matches from spurious ones; together, a
genuine match reliably clears both while a spurious short-name match reliably fails the whole-string floor.
Both defaults were chosen empirically against a sample of real receipt lines run against the real catalog —
including lines with no matching catalog entry at all (e.g. no bare `"Fideos"`, no `"Danbo"` cheese) — not
derived analytically, and are expected to be retuned from observed data.

### `quantity`/`unit` are prefilled only when the printed unit is already the food's base unit

A matched line carries a prefilled `quantity`/`unit` when the printed quantity converts to the matched food's
`base_unit` through the unit conversion module and the food's stored equivalences (ADR-0025). A factor the
food does not have is never guessed: the line is left for the user to fill in.

**The prefill rule** (`app/domain/unit_conversion.py::prefill_from_printed`):

- The extracted `raw_unit_text` is normalized (`app/domain/printed_unit.py::normalize_printed_unit`) to one
  of `g`, `kg`, `ml`, `cl`, `l`, `unidad`. Case, surrounding whitespace and a trailing dot are ignored, and a
  variants table covers the common spellings (`gr`/`grs`/`gramos`, `cc`, `lt`/`lts`/`litro`, `u`/`un`/`unid`,
  …). Anything else — `cucharada`, `taza`, unknown text — does not normalize. The variants table is a starting
  list meant to grow from the spellings seen on real receipts.
- A printed unit of the same dimension as the food's `base_unit` converts with no factor: `500 g` against a
  `kilogramos` food is `0.5`, `33 cl` against a `litros` food is `0.33`.
- A printed unit of another dimension converts through grams and needs the food's factors: `600 g` against a
  `unidades` food that weighs 50 g per unit is `12`. Without that unit weight stored, the line stays empty.
- The result is rounded as a stored quantity: three decimals for `kilogramos` and `litros`, a whole number for
  `unidades`.
- Every other case leaves **both** `quantity` and `unit` `null`: no catalog match, an unsupported or
  unrecognised unit, no unit text at all (a bare count is not assumed to be units), a factor the food does not
  have, an unusable quantity, or a converted quantity that is zero or larger than a line holds
  (`MAX_LINE_QUANTITY`, the same bound quantity parsing uses). The two fields are always null or set together,
  so `unit` is never set merely because a food matched.
- The factors of every matched food in a proposal are read in one query.
- `raw_quantity`/`raw_unit_text` always pass through, so the user can see what was printed whether or not it
  was used.

**Quantity parsing** (`app/domain/printed_quantity.py::parse_printed_quantity`): `raw_quantity` is rounded
half up to three decimals, the precision a proposed line can hold. Text is read as follows:

- A single `,` or `.` is the decimal separator: `1,5` and `1.5` are both 1.5.
- With a comma, dots before it are thousands separators: `1.000,5` is 1000.5.
- Several dots without a comma are thousands separators: `1.000.000` is 1000000.
- A lone dot followed by three digits stays a decimal point: `1.000` is 1. A printed quantity is usually a
  weight with three decimals (`1.250 kg`) rather than a count in the thousands.
- Thousands groups must be exactly three digits; malformed grouping (`1.00.000`, `1.0000,5`) and the
  comma-thousands format (`1,000.5`) are not read as a number.

The quantity is `null` when the value is not a single plain number by those rules, is not finite, is zero or
negative, or exceeds `9999999.999` — typically a barcode or a price read as the quantity. An unusable
quantity only drops that line's quantity; it never fails the response validation of the whole proposal.

## Consequences

**Positives**

- Removes the manual catalog search for the common case (receipt line text closely matches a catalog food
  name), without weakening the review step: the user still explicitly confirms every line.
- Removes the manual quantity entry for matched lines whose printed quantity converts to the food's base unit:
  always within one dimension (`g`, `kg`, `ml`, `cl`, `l`, units), and across dimensions once the food's
  factor is stored.
- Matching needs no schema change, no new table and no LLM prompt change — it reuses `pg_trgm`
  infrastructure the catalog search endpoint already depends on.
- The thresholds are tunable from observed data post-launch without a deploy of new logic.

**Negatives**

- Purely name-similarity based: a receipt abbreviation or brand name with low string similarity to the
  catalog's SARA 2-derived name (e.g. a specific commercial product name vs. a generic SARA 2 entry) will
  not match even when a human would recognize it instantly. Accepted — the fallback is manual search.
- Lines printed in another dimension than the food's base unit (a weight for a food counted in units, a volume
  for a food weighed in kilograms) still need the quantity entered by hand until that food's equivalence is
  stored.
- A lone `1.000` is genuinely ambiguous (1 or 1000); it is read as 1. The quantity is shown for review like
  every other prefilled value.

## Alternatives considered

**Ask the LLM to select from the catalog during extraction** — rejected. Requires sending the full catalog
(hundreds of entries) in every extraction prompt, coupling matching quality to model/prompt behavior instead
of a deterministic, independently testable query, for a lookup Postgres already serves natively via the
existing trigram index.

**Whole-string `similarity()` alone (threshold `0.3`)** — rejected. It under-matched real receipt lines
systematically, including exact substring matches, because the brand and pack-size noise dilutes the score
(see the `"Ketchup"` example above).

**`word_similarity()` alone** — rejected. It fixes the dilution but lets short catalog names (`"Sal"`) match
unrelated lines, sometimes outscoring the genuine match.

**Convert same-dimension units now (e.g. grams to a kilograms `base_unit`)** — rejected for this ADR. Even
the "safe" subset still requires deciding how to handle every other case (no unit text, a dimension mismatch,
an unrecognized unit string) consistently, which is real design work deferred to its own iteration and ADR.
Prefilling only the no-conversion case delivers part of the value without making any of those decisions.
