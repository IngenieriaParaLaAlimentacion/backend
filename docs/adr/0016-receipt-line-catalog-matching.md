# ADR-0016: Trigram-similarity catalog matching for receipt-extracted food lines

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

Matching is done with a Postgres query — `similarity(unaccent(lower(foods.name)), unaccent(lower(description)))`
via the existing `pg_trgm` extension — not by asking the LLM to pick from the catalog during extraction.
Two reasons:

1. **The catalog has hundreds of entries** (SARA 2's full raw/as-purchased list, ADR-0010). Passing the
   full catalog into every Gemini prompt to have the model select from it would meaningfully grow prompt
   size and cost per receipt, for a lookup Postgres already does natively and fast via the existing trigram
   index.
2. **Determinism and testability.** A SQL similarity query is a pure function of `(description, foods.name)`
   at query time — same inputs, same output, and it is trivially unit-testable against a real Postgres
   instance (Testcontainers, consistent with how this codebase tests everything else DB-dependent). An
   LLM-side selection would make matching behavior dependent on model version and prompt phrasing, on top of
   what the extraction step already depends on it for.

### A single configurable similarity threshold decides auto-match vs. leaving `food` null

`FoodRepository.find_best_match(description, min_similarity)` returns the single highest-`similarity()` food
whose score is at or above `min_similarity`, or `None` if nothing clears it. There is no "top-N suggestions"
list — this is a binary decision per line: either the match is confident enough to prefill, or the line is
left exactly as it behaves today (`food=null`), and the user searches manually.

The threshold is a plain setting, `receipt_food_match_min_similarity` (default `0.3`) — not a schema column,
not hardcoded in the query. `0.3` is `pg_trgm`'s own default for its `%` similarity operator
(`pg_trgm.similarity_threshold`), chosen as a starting point precisely because it's the extension's own
judgment call for "these two strings are related enough to be worth surfacing," which is the same bar this
feature needs. Being a setting means it can be tuned from real receipt data (false-positive vs. false-negative
matches) without a migration or a deploy of new query code.

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
