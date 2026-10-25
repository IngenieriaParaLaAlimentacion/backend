import pytest

from app.domain.nutrition import (
    GapaGroup,
    Macronutrient,
    MonthlyIntakeAnalysis,
    PrioritizedNutrient,
)
from app.reference_data.nutrition_references import NINO_7_9
from app.services.nutrition.report_analysis import build_analysis
from tests.unit.nutrition.helpers import monthly_analysis


def test_snapshot_shows_shares_as_percentages_and_flags_what_is_off():
    analysis, milk_id = monthly_analysis()

    snapshot = build_analysis(analysis, NINO_7_9, {milk_id: "Leche"})

    assert snapshot.mean_adequacy_percent == pytest.approx(72)
    calcium, iron = snapshot.nutrients
    assert calcium.adequacy_percent == pytest.approx(44)
    assert (calcium.at_risk, iron.at_risk) == (True, False)
    # Iron is 120% of the reference but counts as 100% toward the mean.
    assert iron.adequacy_percent == pytest.approx(120)
    assert iron.adequacy_capped_percent == pytest.approx(100)
    macros = {m.macro: m for m in snapshot.macros}
    assert macros[Macronutrient.LIPIDS].in_range is False
    assert macros[Macronutrient.LIPIDS].max_percent == pytest.approx(
        NINO_7_9.macro_ranges[Macronutrient.LIPIDS].max_share * 100
    )
    assert macros[Macronutrient.PROTEIN].in_range is True
    groups = {g.group: g for g in snapshot.gapa_groups}
    assert groups[GapaGroup.DAIRY].missing is True
    assert groups[GapaGroup.MEAT_AND_EGGS].missing is False
    assert snapshot.warnings == analysis.warnings


def test_snapshot_names_the_suggested_foods():
    analysis, milk_id = monthly_analysis()

    snapshot = build_analysis(analysis, NINO_7_9, {milk_id: "Leche"})

    [calcium_sources] = snapshot.top_sources
    assert calcium_sources.nutrient == PrioritizedNutrient.CALCIUM
    assert [food.name for food in calcium_sources.foods] == ["Leche"]


def test_month_without_data_keeps_only_the_warnings():
    analysis = MonthlyIntakeAnalysis(has_data=False, warnings=["a gap"])

    snapshot = build_analysis(analysis, NINO_7_9, {})

    assert snapshot.warnings == ["a gap"]
    assert snapshot.energy_kcal is None
    assert snapshot.nutrients == []
