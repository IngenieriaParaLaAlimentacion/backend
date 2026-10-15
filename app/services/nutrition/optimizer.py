from typing import NamedTuple

import pulp

from app.domain.nutrition import (
    FoodQuantity,
    PrioritizedNutrient,
    RecipeSolution,
    ReferenceProfile,
    StockedFood,
    UnmetConstraint,
    UnmetConstraintKind,
)
from app.exceptions.domain_exceptions import RecipeOptimizationError
from app.reference_data.nutrition_references import NINO_7_9
from app.services.nutrition.indicators import (
    ENERGY,
    MACRO_NUTRIENT_CODES,
    calculate_indicators,
    prioritized_amount_per_100g,
)

# Weight of a deviation from a macro range or a GAPA minimum against the gain in
# quality: a 1% deviation costs as much as the whole quality scale.
DEVIATION_PENALTY = 100

# Seconds the solver may take. A recipe model takes a few milliseconds, so reaching
# this means something is wrong with the solver, not that the model is large.
_SOLVER_TIME_LIMIT_SECONDS = 10

# A slack below this is solver noise, not an unmet rule.
_SLACK_TOLERANCE = 1e-4
# A quantity below this many grams is not part of the recipe.
_QUANTITY_TOLERANCE = 1e-6


class _Slack(NamedTuple):
    """How far the recipe may fall short of a soft rule, as a solver variable."""

    kind: UnmetConstraintKind
    subject: str
    variable: pulp.LpVariable
    unit: str


class _SoftRules(NamedTuple):
    """The slacks of a group of soft rules and what each costs in the objective."""

    slacks: list[_Slack]
    penalties: list[pulp.LpAffineExpression]


def maximize_recipe(
    foods: list[StockedFood],
    target_energy_kcal: float,
    profile: ReferenceProfile = NINO_7_9,
) -> RecipeSolution:
    """Choose the grams of each food that make the most balanced recipe.

    The recipe has ``target_energy_kcal`` unless the stock cannot reach it, in
    which case it has all the energy the stock holds and the shortfall is reported
    in ``unmet_constraints``. Macro ranges and GAPA minimums are soft: the closest
    recipe is returned and what it misses is reported. With no energy in stock
    there is nothing to build and ``has_data`` is false.
    """
    usable = [f for f in foods if f.stock_grams > 0]
    # kcal in stock: kcal per 100 g x grams / 100, added up over the foods.
    energy_in_stock = sum(
        f.composition.per_100g.get(ENERGY, 0.0) * f.stock_grams / 100 for f in usable
    )
    if energy_in_stock <= 0:
        return RecipeSolution(has_data=False, target_energy_kcal=target_energy_kcal)

    unmet: list[UnmetConstraint] = []
    # The recipe cannot hold more energy than the stock does.
    energy = min(target_energy_kcal, energy_in_stock)
    if energy < target_energy_kcal:
        unmet.append(
            UnmetConstraint(
                kind=UnmetConstraintKind.STOCK_INSUFFICIENT,
                subject="energy",
                amount=target_energy_kcal - energy,
                unit="kcal",
            )
        )

    # The model is per 1,000 kcal of recipe: it finds the grams per 1,000 kcal of
    # each food, and the recipe quantities are those scaled by energy / 1000.
    grams_per_1000_kcal, unmet_per_1000_kcal = _solve_per_1000_kcal(
        usable, energy, profile
    )

    # From grams per 1,000 kcal to grams of the whole recipe.
    scale = energy / 1000
    quantities = [
        FoodQuantity(food.composition.food_id, grams * scale)
        for food, grams in zip(usable, grams_per_1000_kcal, strict=True)
        if grams * scale > _QUANTITY_TOLERANCE
    ]
    unmet.extend(
        UnmetConstraint(rule.kind, rule.subject, rule.amount * scale, rule.unit)
        for rule in unmet_per_1000_kcal
        if rule.amount > _SLACK_TOLERANCE
    )
    indicators = calculate_indicators(
        quantities, {f.composition.food_id: f.composition for f in usable}, profile
    )
    return RecipeSolution(
        has_data=True,
        quantities=quantities,
        target_energy_kcal=target_energy_kcal,
        energy_kcal=energy,
        indicators=indicators,
        unmet_constraints=unmet,
        warnings=list(indicators.warnings),
    )


def _solve_per_1000_kcal(
    foods: list[StockedFood], energy: float, profile: ReferenceProfile
) -> tuple[list[float], list[UnmetConstraint]]:
    """Solve the linear program and return the grams per 1,000 kcal of each food
    and the soft rules it left unmet, also per 1,000 kcal.
    """
    model = pulp.LpProblem("recipe", pulp.LpMaximize)
    y = _add_quantities(model, foods, energy)
    _add_energy_rule(model, foods, y)
    adequacy = _add_adequacy(model, foods, y, profile)
    macro_rules = _add_macro_ranges(model, foods, y, profile)
    gapa_rules = _add_gapa_minimums(model, foods, y, profile)
    slacks = macro_rules.slacks + gapa_rules.slacks
    penalties = macro_rules.penalties + gapa_rules.penalties

    # Maximize the mean adequacy (0 to 1) minus the weighted deviations, which are
    # also on a 0 to 1 scale, so DEVIATION_PENALTY sets how much each one matters.
    model += pulp.lpSum(adequacy.values()) / len(
        adequacy
    ) - DEVIATION_PENALTY * pulp.lpSum(penalties)

    _solve(model)
    return (
        [v.value() or 0.0 for v in y],
        [
            UnmetConstraint(
                slack.kind, slack.subject, slack.variable.value() or 0.0, slack.unit
            )
            for slack in slacks
        ],
    )


def _add_quantities(
    model: pulp.LpProblem, foods: list[StockedFood], energy: float
) -> list[pulp.LpVariable]:
    """Add the grams of each food per 1,000 kcal, from 0 up to what the stock allows."""
    # The recipe is y scaled by energy / 1000, so the stock, in y units, is the
    # stock grams scaled the other way: stock_grams * 1000 / energy.
    return [
        model.add_variable(f"y_{i}", 0, f.stock_grams * 1000 / energy)
        for i, f in enumerate(foods)
    ]


def _add_energy_rule(
    model: pulp.LpProblem, foods: list[StockedFood], y: list[pulp.LpVariable]
) -> None:
    """Add the hard rule: this model recipe has exactly 1,000 kcal (scaled up later)."""
    # Energy of the recipe: kcal per 100 g of each food x its grams / 100, added up.
    model += _total(y, _amounts_per_100g(foods, ENERGY)) == 1000


def _add_adequacy(
    model: pulp.LpProblem,
    foods: list[StockedFood],
    y: list[pulp.LpVariable],
    profile: ReferenceProfile,
) -> dict[PrioritizedNutrient, pulp.LpVariable]:
    """Add how much of each prioritized nutrient the recipe covers, capped at 100%."""
    adequacy = {}
    for nutrient in PrioritizedNutrient:
        adequacy[nutrient] = model.add_variable(f"u_{nutrient.value}", 0, 1)
        # Amount of the nutrient per 100 g of each food (vitamin A in RE).
        amounts = [
            prioritized_amount_per_100g(nutrient, f.composition.per_100g) or 0.0
            for f in foods
        ]
        # What 1,000 kcal of food should hold of this nutrient.
        reference = profile.nutrient_per_1000_kcal(nutrient)
        # Coverage is at most what the recipe holds divided by what is needed. It is
        # also at most 1 (the variable's bound), which caps the adequacy at 100%.
        model += adequacy[nutrient] <= _total(y, amounts) / reference
    return adequacy


def _add_macro_ranges(
    model: pulp.LpProblem,
    foods: list[StockedFood],
    y: list[pulp.LpVariable],
    profile: ReferenceProfile,
) -> _SoftRules:
    """Add the soft range of the energy share of each macronutrient.

    Each rule carries a slack for how far the recipe falls short of it.
    """
    slacks = []
    penalties = []
    for macro, (code, kcal_per_gram) in MACRO_NUTRIENT_CODES.items():
        below = model.add_variable(f"s_{macro.value}_below", 0)
        above = model.add_variable(f"s_{macro.value}_above", 0)
        # Energy this macro gives per 1,000 kcal of recipe: its grams x kcal per gram.
        kcal = kcal_per_gram * _total(y, _amounts_per_100g(foods, code))
        allowed = profile.macro_ranges[macro]
        # The share of the energy is kcal / 1,000, so its range is scaled by 1,000.
        # Keep the share in its range: below fills a shortfall, above an excess.
        model += kcal + below >= allowed.min_share * 1000
        model += kcal - above <= allowed.max_share * 1000
        # Over 1,000 kcal, so 10 kcal out of range weigh 0.01.
        penalties.append((below + above) / 1000)
        slacks.append(
            _Slack(UnmetConstraintKind.MACRO_BELOW_MIN, macro.value, below, "kcal")
        )
        slacks.append(
            _Slack(UnmetConstraintKind.MACRO_ABOVE_MAX, macro.value, above, "kcal")
        )
    return _SoftRules(slacks, penalties)


def _add_gapa_minimums(
    model: pulp.LpProblem,
    foods: list[StockedFood],
    y: list[pulp.LpVariable],
    profile: ReferenceProfile,
) -> _SoftRules:
    """Add the soft minimum grams of each GAPA group the profile asks for.

    Each rule carries a slack for how far the recipe falls short of it.
    """
    slacks = []
    penalties = []
    for group in profile.gapa_portions:
        minimum = profile.gapa_minimum_per_1000_kcal(group)
        if minimum <= 0:
            continue
        short = model.add_variable(f"s_{group.value}", 0)
        members = [
            v
            for f, v in zip(foods, y, strict=True)
            if f.composition.gapa_group == group
        ]
        # The foods of the group must add up to its minimum grams; short fills the gap.
        model += pulp.lpSum(members) + short >= minimum
        # Over the minimum, so missing half of it weighs 0.5 whatever the group.
        penalties.append(short / minimum)
        slacks.append(
            _Slack(UnmetConstraintKind.GAPA_GROUP_BELOW_MIN, group.value, short, "g")
        )
    return _SoftRules(slacks, penalties)


def _solve(model: pulp.LpProblem) -> None:
    """Solve the model, raising unless the solver proves an optimum."""
    model.solve(pulp.HiGHS(msg=False, timeLimit=_SOLVER_TIME_LIMIT_SECONDS))
    solver_status = pulp.LpStatus[model.status]
    # PuLP reports "Optimal" even when the time limit cut the solve short;
    # sol_status tells a proven optimum from a merely feasible solution.
    if solver_status == "Optimal" and model.sol_status != pulp.LpSolutionOptimal:
        solver_status = "Feasible, not proven optimal"
    if solver_status != "Optimal":
        # The stock check makes the program feasible, so this is a solver failure.
        raise RecipeOptimizationError(solver_status)


def _amounts_per_100g(foods: list[StockedFood], code: str) -> list[float]:
    """Return the amount of a catalog nutrient per 100 g of each food."""
    return [f.composition.per_100g.get(code, 0.0) for f in foods]


def _total(
    y: list[pulp.LpVariable], amounts_per_100g: list[float]
) -> pulp.LpAffineExpression:
    """Sum of a nutrient over the recipe, per 1,000 kcal."""
    # Each term is the amount per 100 g x the grams eaten / 100.
    return pulp.lpSum(a * v / 100 for a, v in zip(amounts_per_100g, y, strict=True))
