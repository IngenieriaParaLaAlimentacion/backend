# ADR-0014: Materialized food stock per establishment

- **Status**: Accepted
- **Date**: 2026-09-05
- **Deciders**: Backend team
- **Related**: ADR-0012 (food catalog relational schema), ADR-0013 (food intake
  relational schema), ADR-0004 (offline-first sync via client ids)

## Context

ADR-0013 modeled what an establishment *receives* and stopped there, noting explicitly that no
stock or balance concept was included: "this entity records what arrived; what is currently held
(consumption, spoilage, running balance) is a separate question". This ADR answers that question.

Two things forced it now:

1. **The `nutrir` module needs the balance, not the history.** AI-assisted meal planning starts from
   the ingredients a kitchen actually has. That is a frequent read of a single point-in-time value
   per establishment, not a traversal of every movement ever recorded.
2. **A balance that can go negative is not a balance.** If an outflow can be recorded for food that
   is not there, whatever is read out of the system afterwards is not "what the kitchen has".

## Decision

### Two movement tables plus one balance table

`food_outflows` / `food_outflow_items` mirror `food_intakes` / `food_intake_items` exactly — same
header/lines split, same `RESTRICT` on establishment and user, `CASCADE` on lines, `Numeric(10,3)`
with `CHECK (quantity > 0)`, client-generatable UUID and `synced_at` for the offline path. An
outflow is deliberately **untyped**: no consumption/waste/adjustment taxonomy. Nothing defined today
distinguishes them, and a reason column is additive if something ever does.

`food_stock` holds one row per `(establishment_id, food_id)` with a `quantity` and a
`CHECK (quantity >= 0)`, unique on the pair.

### The balance is materialized, not derived

The alternative — computing `SUM(intakes) − SUM(outflows)` on every read — is more auditable and
cannot drift. It was rejected because the intended consumer reads the balance far more often than
anything reads the movements, and because a derived balance makes the negative-stock guard expensive
exactly where it has to be cheap: on every write.

The cost accepted is drift risk, and it is paid for by `FoodStockRepository.recompute`, which
rebuilds an establishment's balances from its movements. An integration test asserts that recompute
changes nothing after a mixed sequence of movements — the materialized and derived answers must
agree.

### Both movements are single statements

An intake upserts (`INSERT ... ON CONFLICT DO UPDATE SET quantity = quantity + :q`); an outflow
updates conditionally (`UPDATE ... SET quantity = quantity - :q WHERE ... AND quantity >= :q`), and
a rowcount of zero *is* the insufficient-stock signal.

This is the load-bearing choice. Reading the balance, deciding in Python, then writing it back would
let two concurrent outflows both observe the same balance and both spend it. Letting Postgres do the
arithmetic and the comparison in place cannot: the second `UPDATE` waits on the row lock and then
re-evaluates its own `WHERE` against the value the first one left. The service reads the balance
**only** on the failure path, to say how much is actually available.

### Replays must not move the balance

Both services short-circuit a client-generated id that already exists and return before touching the
stock. With a materialized balance this stops being a nicety: applying a re-sent intake twice
inflates the stock permanently, with nothing in the movement tables to explain the discrepancy.
This is the single most important correctness condition of the design.

### The balance is "now", never "as of"

Movements carry `received_at` / `occurred_at` independent of `created_at`, so retroactive loads are
representable. Addition is commutative, so late arrivals do not corrupt the final balance — but the
409 is evaluated against the balance *at the moment of writing*, not at `occurred_at`. A retroactive
outflow can therefore be refused even though stock existed on its own date. Answering "what did this
kitchen hold on the 3rd" requires aggregating the movements; `food_stock` cannot answer it.

## Consequences

*Positives*

- Reading an establishment's stock is one indexed query over one row per food — the shape `nutrir`
  needs.
- Stock cannot go negative: enforced by the conditional update, by a `CHECK` constraint underneath
  it, and surfaced as a 409 that names the food, the requested amount and the available one.
- An outflow whose second line is short rolls back its first: the service raises inside the
  UnitOfWork, so a half-spent outflow is never persisted.
- A depleted food keeps a zero row. "Never received" and "ran out" stay distinguishable, which
  matters for meal suggestions.
- Lines still carry no unit; it is read from `foods.base_unit` per ADR-0012, so the balance and the
  catalog cannot disagree.

*Negatives*

- The balance can drift from the movements if any future write path forgets to move it. `recompute`
  is the remedy, but nothing forces a new caller to use the services rather than the repositories.
- There is no delete path for a movement. If one is added it must reverse the balance, and no
  constraint enforces that today.
- A historical balance is not available from this table, only the current one.
- `ON CONFLICT DO UPDATE` is the first use of a Postgres-specific upsert in this codebase, which
  narrows portability that was already narrow (the schema uses native enums and `DISTINCT ON`).

*Neutral*

- Outflows carry no reason. If reporting ever needs to separate consumption from waste, a nullable
  `reason` enum column on `food_outflows` is additive.
- No transfers between establishments. A transfer would be an outflow and an intake that must
  succeed or fail together across two balances — a different transactional problem, deliberately
  out of scope.

## Alternatives considered

**Derived balance, computed per read** — rejected as above: wrong shape for the primary consumer,
and it makes the write-time guard expensive. It remains the right answer for a historical balance,
which is why `recompute` implements exactly that query.

**Derived plus periodic month-end snapshots** — the classic accounting solution, rejected as
premature: it adds a closing process and a reconciliation story for a data volume this system does
not have.

**`SELECT ... FOR UPDATE` then write** — rejected. It is correct, but it holds a row lock across two
round trips for something a single statement decides atomically, and it invites a caller to read the
balance, act on it, and write back outside the lock.

**A signed-quantity `food_movements` table replacing both intakes and outflows** — rejected. It
would collapse `food_intakes`, already delivered and referenced by ADR-0013, into a rewrite, and a
signed quantity gives up the `CHECK (quantity > 0)` that catches a nonsense line at the boundary.
