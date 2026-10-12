# ADR-0017: Trigram-similarity catalog matching for receipt-extracted food lines

- **Status**: Accepted
- **Date**: 2026-09-19
- **Deciders**: Backend team
- **Related**: ADR-0015 (receipt photo storage — the propose/confirm flow this ADR extends), ADR-0012 (food
  catalog relational schema — the source of `foods.base_unit` and the explicit non-goal this ADR reaffirms
  for the receipt-intake case), ADR-0010 (SARA 2 as the catalog source)

## Context

`POST /food-intakes/from-photo` extracts a list of food lines from a receipt photo via an LLM call (Gemini).
Each proposed line comes back with a free-text `description` read off the receipt (e.g. `"Arroz 1kg"`), but
`ProposedFoodLine.food` — the catalog match the user would otherwise have to search for by hand — is never
populated: every line always comes back with `food=null`, forcing the user to search and pick the matching
catalog entry themselves for every single line, even when the receipt text is an unambiguous match for an
existing `foods` row (e.g. `"Arroz 1kg"` against the catalog entry `"Arroz"`).

The food catalog (ADR-0010, ADR-0012) already has catalog-wide fuzzy search: `pg_trgm` is enabled
(`eb850f66c679`), `foods.name` has a trigram index (`4099691d9bcd`), and `FoodRepository` already orders
catalog listing results by `similarity()` when a user types a search term
([food_repository.py:39-49](../../app/repositories/food_catalog/food_repository.py#L39-L49)). That
machinery ranks a human-typed query; it has never been used to make an automated, unattended matching
decision.

This ADR settles how a raw receipt-line description gets turned into a catalog `food` reference, and how
confident that match has to be before it's shown to the user as already resolved.

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
line: either the match is confident enough to prefill, or the line is left exactly as it behaves today
(`food=null`), and the user searches manually.

Both thresholds are plain settings — not schema columns, not hardcoded in the query — tunable from real
receipt data without a migration or a deploy of new query code:

- `receipt_food_match_min_word_similarity` (default `0.5`): the primary signal. `word_similarity` scores a
  catalog name against its best-matching contiguous extent of the description, so it isn't diluted by a
  brand name or pack size elsewhere in the line the way whole-string `similarity` is (see "Amendment" below).
- `receipt_food_match_min_similarity` (default `0.22`): a whole-string `similarity` floor applied alongside
  it. `word_similarity` alone is a poor filter for *short* catalog names (e.g. `"Sal"`) — a short name can
  score deceptively high against some coincidental extent of an unrelated, noisy line. A genuine match also
  carries non-trivial whole-string overlap with the full description; a short spurious match doesn't. This
  floor exists specifically to reject that case.

Both defaults were tuned empirically against a sample of real receipt lines and the actual food catalog
(`app/reference_data/foods.csv`) rather than derived analytically — see "Amendment" below.

### `needs_review` stays `true` unconditionally — matching never marks a line as resolved

A confident catalog match does **not** flip `needs_review` to `false`. Every proposed line, matched or not,
still requires the user's explicit confirmation before `POST /food-intakes/from-photo/confirm` can persist
it. This is a deliberate choice, not a placeholder: this data feeds establishment stock levels for a food
security platform, and a wrong auto-match silently accepted would corrupt that stock. `needs_review` is kept
as a single, unconditional signal ("a human must look at every line") rather than becoming a
per-line trust signal that a caller could reasonably start skipping past.

### Unit conversion is explicitly out of scope for this ADR

Matching only ever sets `ProposedFoodLine.food`. It does **not** attempt to populate `quantity`/`unit` from
the already-captured `raw_quantity`/`raw_unit_text` — those stay `null`, exactly as they are today, for
every line regardless of whether a catalog match was found. This reaffirms, for the receipt-intake case
specifically, the general non-goal ADR-0012 already recorded: SARA 2 provides no purchasing-unit or
weight-per-unit data, so there is no sourced way to convert a receipt-printed quantity (which may be in a
different unit, or a different physical dimension entirely — a bare count vs. a weight) into the matched
food's `base_unit` without inventing a conversion factor. Solving that is deferred to a future, separately
scoped iteration once there's a concrete answer for where a same-dimension unit conversion (e.g. printed
grams to a kilograms-based `base_unit`) is sourced from and how a dimension mismatch (a count printed
against a weight-based food) should be handled.

## Consequences

**Positives**

- Removes the manual catalog search for the common case (receipt line text closely matches a catalog food
  name), without weakening the review step: the user still explicitly confirms every line.
- No schema change, no new table, no LLM prompt change — reuses `pg_trgm` infrastructure the catalog search
  endpoint already depends on.
- The threshold is tunable from observed data post-launch without a deploy of new logic.

**Negatives**

- Purely name-similarity based: a receipt abbreviation or brand name with low string similarity to the
  catalog's SARA 2-derived name (e.g. a specific commercial product name vs. a generic SARA 2 entry) will
  not match even when a human would recognize it instantly. Accepted for this iteration — the fallback is
  exactly today's behavior (manual search).
- `quantity`/`unit` remain unresolved even for a matched line, so the user still has to enter a quantity by
  hand for every line, matched or not — this ADR only removes the catalog-search step, not the
  quantity-entry step.

**Neutral**

- `needs_review` remaining unconditionally `true` means the field currently carries no information beyond
  "there is at least one line in this proposal" — revisited once unit conversion (or another per-line
  resolution signal) is designed.

## Alternatives considered

**Ask the LLM to select from the catalog during extraction** — rejected. Requires sending the full catalog
(hundreds of entries) in every extraction prompt, coupling matching quality to model/prompt behavior instead
of a deterministic, independently testable query, for a lookup Postgres already serves natively via the
existing trigram index.

**Flip `needs_review` to `false` on a confident match** — rejected for now. Considered as the literal reading
of the field ("does the user need to fix something"), but rejected because this data writes directly to
establishment stock and the last validation before that write should always be a human's, not a similarity
score's. May be revisited alongside a broader per-line resolution model once unit conversion is designed.

**Attempt unit conversion now, scoped only to same-dimension cases (e.g. grams to a kilograms `base_unit`)**
— rejected for this ADR. Even the "safe" subset still requires deciding how to handle every other case (no
unit text, a dimension mismatch, an unrecognized unit string) consistently, which is real design work
deferred to its own iteration rather than bundled into the matching decision this ADR is scoped to.

## Amendment (2026-10-12): `quantity`/`unit` are prefilled when the printed unit is already the food's base unit

The "Unit conversion is explicitly out of scope" section above no longer holds in full: a matched line can now
carry a prefilled `quantity`/`unit`. Conversion itself is still out of scope, and the "attempt unit conversion
now" alternative stays rejected — the prefill only happens when no conversion is needed.

**The prefill rule** (`app/domain/printed_unit.py::prefill_from_printed`):

- The extracted `raw_unit_text` is normalized to one of `g`, `kg`, `ml`, `cl`, `l`, `unidad`. Case, surrounding
  whitespace and a trailing dot are ignored, and a variants table covers the common spellings (`gr`/`grs`/
  `gramos`, `cc`, `lt`/`lts`/`litro`, `u`/`un`/`unid`, …). Anything else — `cucharada`, `taza`, unknown text —
  does not normalize.
- A matched line is prefilled only when the normalized unit is exactly the matched food's `base_unit`:
  `kg` for a `kilogramos` food, `l` for `litros`, `unidad` for `unidades`. The quantity is taken as printed.
- `g`, `ml` and `cl` are recognised but never prefilled, since reaching a kilograms or litres `base_unit` would
  be a conversion. A line printed as `500 g` against a kilograms food stays empty until unit conversion is
  designed.
- Every other case leaves **both** `quantity` and `unit` `null`: no catalog match, an unsupported or
  unrecognised unit, no unit text at all (a bare count is not assumed to be units), a dimension mismatch
  (`1 kg` against a `unidades` food), or an unusable quantity. The two fields are always null or set
  together, so `unit` is no longer set merely because a food matched.
- `raw_quantity`/`raw_unit_text` always pass through, so the user can see what was printed whether or not it
  was used.

**Quantity parsing** (`app/domain/printed_quantity.py::parse_printed_quantity`): `raw_quantity` is accepted
with either `,` or `.` as the decimal separator and rounded half up to three decimals, the precision a
proposed line can hold. It is `null` when the value is not a single plain number (including a grouped
`1.000,5`, which is ambiguous), is not finite, is zero or negative, or exceeds `9999999.999` — typically a
barcode or a price read as the quantity. Such a value used to fail the response validation and discard the
whole proposal; now only that line loses its quantity.

`needs_review` is unchanged: the user still confirms every line, and nothing is saved automatically. The
variants table is a starting list meant to grow from the spellings seen on real receipts.

**Consequence**: lines printed in `g`, `ml` or `cl` — common on receipts — still need the quantity entered by
hand. This is the cost of not converting, and it goes away once unit conversion and per-food equivalences
are designed.

## Amendment (2026-09-19): whole-string `similarity()` under-matched real receipt lines

Testing the original decision (plain `similarity()`, threshold `0.3`) against real receipt photos surfaced a
systematic false-negative problem, not just the anticipated brand-name edge case: lines like
`"Ketchup HELLMANNS x250g DOY 237 gr. (21,00)"` failed to match `"Ketchup"` even though the catalog name is a
perfect substring of the line. `similarity()` is a Jaccard-like ratio over the *union* of both strings'
trigrams — a short catalog name compared against a long, brand-and-pack-noisy line gets diluted by the extra
trigrams the noise contributes to that union, regardless of how well the actual product name matches. This
was not an edge case: it affected the majority of lines in a real receipt, including exact substring matches.

Switching to `word_similarity()` (which scores a name against its best-matching contiguous *extent* of the
other string, rather than the whole-string union) fixes that dilution — but probing it against the full real
catalog (`app/reference_data/foods.csv`, ~900 rows) showed it introduces the opposite failure mode: a *short*
catalog name (e.g. `"Sal"`) can score deceptively high (0.5–0.75) against a coincidental extent of a
completely unrelated line, sometimes outscoring genuine matches. Neither function alone gives a threshold that
cleanly separates real matches from spurious ones across the sample tested.

The fix adopted (see "Decision" above) requires both scores to clear independent floors:
`word_similarity() >= 0.5` as the primary match signal, gated by `similarity() >= 0.22` specifically to reject
the short-name false-positive case, since a genuine match reliably clears both while a spurious short-name
match reliably fails the whole-string floor. Both values were chosen empirically against a sample of real
receipt lines run against the real catalog — including cases where the catalog does not have a matching entry
at all (e.g. no bare `"Fideos"`, no `"Danbo"` cheese) — not derived analytically; they're the kind of thing
the "Negatives" section above already expected to need retuning from observed data.
