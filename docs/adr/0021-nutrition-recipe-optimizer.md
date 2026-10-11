# ADR-0021: Recipe optimizer as a linear program solved with PuLP

- **Status**: Accepted
- **Date**: 2026-10-11
- **Deciders**: Backend team
- **Related**: Issue #169 (nutrition calculation service), ADR-0020

## Context

Given the foods an establishment holds, the service has to suggest how much of each to cook so that the recipe is
as balanced as possible: it covers the prioritized micronutrients, keeps the macronutrients in range and
includes every GAPA group. The suggestion must never use more than the stock, must have the energy the children
need, and must say what it could not satisfy instead of failing.

## Decision

### A continuous linear program, per 1,000 kcal

- Variables are the grams `y_i` of each food **per 1,000 kcal of recipe**, plus the capped adequacy `u_n` of
  each prioritized nutrient and slacks for the soft rules. The recipe is `y` scaled by `energy / 1000`, in code.
- **Hard**: the model recipe has exactly 1,000 kcal, and each food stays within its stock.
- **Soft**, with a slack that is penalized and reported: each macronutrient's energy share range and one minimum
  in grams per GAPA group 1 to 5. A group with no food in stock keeps its slack and is reported the same way.
- **Objective**: maximize the mean of the seven `u_n` (each at most its adequacy and at most 1) minus
  `DEVIATION_PENALTY = 100` times the weighted slacks. It is the same indicator the rest of the service reports:
  the mean adequacy ratio, capped so an excess does not make up for a deficit.
- Fiber, sodium, saturated fat and added sugar are not constraints; they are indicators of the final recipe.
- There is no cap per food. A very nutritious food can take a large share; whoever reads the recipe corrects it.
- The result is not required to be deterministic. Any optimal recipe is valid, so tests check properties
  (energy, stock, reported shortfalls) and not exact grams.

### The model

Data, all per the food as the catalog weighs it:

| Symbol | Meaning |
| --- | --- |
| `i` | A food with stock, `S_i` its grams in stock |
| `e_i` | kcal per 100 g of food `i` |
| `c_in` | Amount of nutrient `n` per 100 g of food `i` (vitamin A in retinol equivalents, `2 × RAE − retinol`) |
| `q_im`, `k_m` | Grams of macronutrient `m` per 100 g of food `i`, and its kcal per gram (protein 4, fat 9, carbohydrates 4) |
| `R_n` | What 1,000 kcal of food should hold of nutrient `n` (ADR-0020) |
| `[α_m, β_m]` | Range of the energy share of macronutrient `m` |
| `D_g` | Minimum grams of GAPA group `g` per 1,000 kcal: daily portions × grams per portion / 1,770 × 1,000 |
| `G_g` | The foods of group `g` (groups 1 to 5; the optional group has no minimum) |
| `E` | Energy of the recipe: `min(target, Σ e_i S_i / 100)` |
| `λ` | `DEVIATION_PENALTY`, 100 |

Variables, all non-negative:

- `y_i`: grams of food `i` per 1,000 kcal of recipe, at most `S_i × 1,000 / E`.
- `u_n`: coverage of nutrient `n`, at most 1.
- `s_m⁻`, `s_m⁺`: kcal that macronutrient `m` falls below or goes over its range, per 1,000 kcal.
- `s_g`: grams that group `g` falls short of its minimum, per 1,000 kcal.

Constraints:

```
(1) Σ_i e_i y_i / 100 = 1000                        the model recipe has 1,000 kcal
(2) u_n ≤ Σ_i c_in y_i / (100 R_n)                   coverage ≤ amount held / amount needed
(3) k_m Σ_i q_im y_i / 100 + s_m⁻ ≥ 1000 α_m        macro share at least its floor
(4) k_m Σ_i q_im y_i / 100 − s_m⁺ ≤ 1000 β_m        macro share at most its ceiling
(5) Σ_{i ∈ G_g} y_i + s_g ≥ D_g                     group at least its minimum
```

Objective:

```
maximize   (1/7) Σ_n u_n  −  λ ( Σ_m (s_m⁻ + s_m⁺) / 1000  +  Σ_g s_g / D_g )
```

Reading it:

- The objective rises with each `u_n`, and (2) only caps it, so at the optimum `u_n = min(1, amount held /
  amount needed)`: the capped adequacy ratio, without writing a `min`, which is not linear.
- Dividing macro slacks by 1,000 makes them a fraction of the energy, and dividing group slacks by `D_g` makes
  them a fraction of the minimum, so both weigh on the same scale: missing half of a minimum costs `λ / 2`.
- A slack is above zero only when the rule cannot be met with the stock: the program prefers any recipe that
  meets a rule over one that gains coverage by breaking it, as far as `λ` allows.

Afterwards, in code:

- The recipe is `x_i = y_i × E / 1,000` grams of each food, dropping those below a microgram.
- Each slack above a small tolerance becomes an unmet constraint, scaled the same way (`s × E / 1,000`), in kcal
  for macros and grams for groups.
- Foods with no energy (salt, for example) have `e_i = 0`: they do not enter (1), so the model may take any
  amount of them up to their stock if they raise a coverage.

### Energy and stock are checked outside the program

The energy asked for is `children × 1,770 kcal × the meal's share`. Before solving, the energy the stock holds
is added up. If it falls short, the recipe is built with all of it and the gap is reported as an unmet
constraint; if it holds none, there is no recipe (`has_data` false). With that check the program is always
feasible, so any other solver outcome is an error, not a result to explain.

### Solver

**PuLP 3.x with its bundled CBC**, called from a worker thread so the event loop is not blocked. PuLP 4 needs
Python 3.12 and the image runs 3.11, so the dependency is `pulp@^3.3`. Its calls for CBC and for creating
variables are deprecated in PuLP 4; variables are created with `add_variable`, and the CBC call is the one that
changes with the image.

### Data the program needs

The GAPA minimums and the meal shares of the energy are part of the reference profile (ADR-0020). The grams per
portion of groups 1, 4 and 5 and the meal shares are provisional.

## Consequences

- The model is written with named variables and constraints, close to its mathematical statement, and the slacks
  are read by name to build the unmet constraints.
- With `DEVIATION_PENALTY = 100`, a deviation of 1% of a macro costs as much as the whole quality scale, so
  smaller deviations can still be traded for quality: the priority is not strict. Making it strict means a
  larger weight or two solves (first the slacks, then the quality). Not needed so far; it is a value to validate
  with the nutritionists.
- GAPA minimums use the weight of the food as the catalog gives it, so a cereal counted raw weighs less than the
  cooked portion of the manual. The minimum is lower than the cooked one, on purpose.
- Everything is in grams. Converting from each food's `base_unit` is #155 and enters through the
  `GramsConverter`; a food with no conversion is left out and reported.
- The solver runs one CBC process per request.

## Alternatives considered

- **`scipy.optimize.linprog`.** Rejected: constraints are written as matrices by index, which is easy to get
  wrong, and slacks cannot be read by name.
- **A greedy heuristic.** Rejected: it does not guarantee the optimum and cannot explain what a recipe could not
  satisfy.
- **Binary variables to require that each group appears.** Rejected: a minimum in grams expresses the same rule
  without making the problem integer.
- **Strict priority with two solves.** Not adopted yet; see the consequences.
