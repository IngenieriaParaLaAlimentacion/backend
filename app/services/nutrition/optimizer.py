import pulp

from app.domain.nutrition import (
    FoodQuantity,
    PrioritizedNutrient,
    RecipeSolution,
    StockedFood,
    UnmetConstraint,
    UnmetConstraintKind,
)
from app.exceptions.domain_exceptions import RecipeOptimizationError
from app.reference_data.nutrition_references import NINO_7_9, ReferenceProfile
from app.services.nutrition.indicators import (
    ENERGY,
    MACRO_NUTRIENT_CODES,
    calculate_indicators,
    prioritized_amount_per_100g,
)

# Weight of a deviation from a macro range or a GAPA minimum against the gain in
# quality: a 1% deviation costs as much as the whole quality scale.
DEVIATION_PENALTY = 100

# A slack below this is solver noise, not an unmet rule.
_SLACK_TOLERANCE = 1e-4
# A quantity below this many grams is not part of the recipe.
_QUANTITY_TOLERANCE = 1e-6


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
    energy_in_stock = sum(
        f.composition.per_100g.get(ENERGY, 0.0) * f.stock_grams / 100 for f in usable
    )
    if energy_in_stock <= 0:
        return RecipeSolution(has_data=False, target_energy_kcal=target_energy_kcal)

    unmet: list[UnmetConstraint] = []
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

    # The model is per 1,000 kcal of recipe: y are grams per 1,000 kcal, and the
    # recipe quantities are y scaled by energy / 1000.
    y, slacks = _solve_per_1000_kcal(usable, energy, profile)

    scale = energy / 1000
    quantities = [
        FoodQuantity(food.composition.food_id, grams * scale)
        for food, grams in zip(usable, y, strict=True)
        if grams * scale > _QUANTITY_TOLERANCE
    ]
    unmet.extend(
        UnmetConstraint(kind, subject, amount * scale, unit)
        for kind, subject, amount, unit in slacks
        if amount > _SLACK_TOLERANCE
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
) -> tuple[list[float], list[tuple[UnmetConstraintKind, str, float, str]]]:
    """Solve the linear program and return the grams per 1,000 kcal of each food
    and every slack as ``(kind, subject, amount, unit)``.
    """
    model = pulp.LpProblem("recipe", pulp.LpMaximize)
    # y[i]: grams of food i per 1,000 kcal, from 0 up to what the stock allows.
    y = [
        model.add_variable(f"y_{i}", 0, f.stock_grams * 1000 / energy)
        for i, f in enumerate(foods)
    ]

    def per_100g(code: str) -> list[float]:
        """Amount of a nutrient per 100 g of each food, in the order of ``foods``."""
        return [f.composition.per_100g.get(code, 0.0) for f in foods]

    def total(coefficients: list[float]):
        """Sum of a nutrient over the recipe, per 1,000 kcal."""
        return pulp.lpSum(c * v / 100 for c, v in zip(coefficients, y, strict=True))

    # Hard rule: this model recipe has exactly 1,000 kcal (scaled up afterwards).
    model += total(per_100g(ENERGY)) == 1000

    # adequacy[n]: how much of nutrient n the recipe covers, capped at 100%.
    adequacy = {}
    for nutrient in PrioritizedNutrient:
        adequacy[nutrient] = model.add_variable(f"u_{nutrient.value}", 0, 1)
        # Amount of the nutrient per 100 g of each food (vitamin A in RE).
        coefficients = [
            prioritized_amount_per_100g(nutrient, f.composition.per_100g) or 0.0
            for f in foods
        ]
        # What 1,000 kcal of food should hold of this nutrient.
        reference = profile.nutrient_per_1000_kcal(nutrient)
        # Coverage is at most what the recipe holds divided by what is needed.
        model += adequacy[nutrient] <= total(coefficients) / reference

    # Soft rules carry a slack: how far the recipe falls short of the rule.
    # Each slack is penalized in the objective and reported if it ends above zero.
    penalty = []
    slacks = []
    for macro, (code, kcal_per_gram) in MACRO_NUTRIENT_CODES.items():
        below = model.add_variable(f"s_{macro.value}_below", 0)
        above = model.add_variable(f"s_{macro.value}_above", 0)
        # Energy this macro gives per 1,000 kcal of recipe.
        kcal = kcal_per_gram * total(per_100g(code))
        allowed = profile.macro_ranges[macro]
        # Keep the share in its range: below fills a shortfall, above an excess.
        model += kcal + below >= allowed.min_share * 1000
        model += kcal - above <= allowed.max_share * 1000
        # Over 1,000 kcal, so 10 kcal out of range weigh 0.01.
        penalty.append((below + above) / 1000)
        slacks.append((UnmetConstraintKind.MACRO_BELOW_MIN, macro.value, below, "kcal"))
        slacks.append((UnmetConstraintKind.MACRO_ABOVE_MAX, macro.value, above, "kcal"))

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
        penalty.append(short / minimum)
        slacks.append(
            (UnmetConstraintKind.GAPA_GROUP_BELOW_MIN, group.value, short, "g")
        )

    # Maximize the mean adequacy minus the weighted deviations.
    model += pulp.lpSum(adequacy.values()) / len(
        adequacy
    ) - DEVIATION_PENALTY * pulp.lpSum(penalty)

    model.solve(pulp.PULP_CBC_CMD(msg=False))
    solver_status = pulp.LpStatus[model.status]
    if solver_status != "Optimal":
        # The stock check makes the program feasible, so this is a solver failure.
        raise RecipeOptimizationError(solver_status)

    return (
        [v.value() or 0.0 for v in y],
        [
            (kind, subject, var.value() or 0.0, unit)
            for kind, subject, var, unit in slacks
        ],
    )
