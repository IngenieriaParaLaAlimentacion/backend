import csv
import uuid
from pathlib import Path

from app.domain.nutrition import FoodComposition, GapaGroup

REFERENCE_DATA = Path(__file__).parents[3] / "app" / "reference_data"


def composition(
    per_100g: dict[str, float], group: GapaGroup | None = None
) -> FoodComposition:
    """A catalog food with the given nutrients per 100 g and an optional group."""
    return FoodComposition(food_id=uuid.uuid4(), gapa_group=group, per_100g=per_100g)


def read_reference_csv(name: str) -> list[dict]:
    """The rows of a CSV in ``app/reference_data``."""
    with open(REFERENCE_DATA / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def monthly_analysis():
    """A month with a calcium shortfall, lipids over their range and no dairy.

    Returns the analysis and the id of the food suggested for calcium.
    """
    from app.domain.nutrition import (
        FoodSource,
        GapaGroup,
        LimitIndicator,
        Macronutrient,
        MacroOutOfRange,
        MonthlyIntakeAnalysis,
        NutrientAdequacy,
        NutritionIndicators,
        PrioritizedNutrient,
    )

    milk_id = uuid.uuid4()
    indicators = NutritionIndicators(
        has_data=True,
        energy_kcal=250000.0,
        nutrients=[
            NutrientAdequacy(PrioritizedNutrient.CALCIUM, 310.0, 0.44, 0.44),
            NutrientAdequacy(PrioritizedNutrient.IRON, 5.0, 1.2, 1.0),
        ],
        mean_adequacy_ratio=0.72,
        macro_energy_share={
            Macronutrient.PROTEIN: 0.12,
            Macronutrient.LIPIDS: 0.33,
            Macronutrient.CARBOHYDRATES: 0.55,
        },
        gapa_energy_share={
            group: 0.0 if group == GapaGroup.DAIRY else 0.25 for group in GapaGroup
        },
        limit_indicators=[LimitIndicator("sodio", 800.0)],
    )
    analysis = MonthlyIntakeAnalysis(
        has_data=True,
        indicators=indicators,
        nutrients_at_risk=[PrioritizedNutrient.CALCIUM],
        macros_out_of_range=[MacroOutOfRange(Macronutrient.LIPIDS, 0.33, 0.15, 0.30)],
        missing_gapa_groups=[GapaGroup.DAIRY],
        top_sources={
            PrioritizedNutrient.CALCIUM: [FoodSource(milk_id, amount_per_100_kcal=180)]
        },
        warnings=["1 food(s) have no value for zinc, counted as 0"],
    )
    return analysis, milk_id
