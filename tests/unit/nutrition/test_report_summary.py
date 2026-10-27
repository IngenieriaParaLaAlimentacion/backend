import json
import uuid

import pytest
from pydantic import ValidationError

from app.domain.nutrition import PrioritizedNutrient
from app.domain.nutrition_report import SUMMARY_MAX_ITEMS, SUMMARY_TEXT_MAX_LENGTH
from app.schemas.nutrition.nutrition_report_schema import (
    NutritionReportAnalysis,
    NutritionReportSummary,
    ReportFoodSource,
    ReportFoodWithoutConversion,
    ReportNutrientSources,
)
from app.services.nutrition.report_summary import (
    RESPONSE_SCHEMA,
    build_prompt,
    parse_summary,
)


def summary_of(**overrides) -> dict:
    return {
        "overview": "El mes estuvo equilibrado.",
        "at_risk_nutrients": ["Calcio: 44% de lo esperado."],
        "macros": "Dentro de los rangos.",
        "gapa_groups": "Falta el grupo de lácteos.",
        "incorporate": "Sumar leche.",
        "limitations": [],
        **overrides,
    }


def context_of(prompt: str) -> dict:
    return json.loads(prompt.split("Context:\n")[1])


def test_prompt_gives_the_calculated_figures_without_internal_food_ids():
    food_id = uuid.uuid4()
    left_out_id = uuid.uuid4()
    analysis = NutritionReportAnalysis(
        energy_kcal=1234.5,
        foods_without_conversion=[
            ReportFoodWithoutConversion(food_id=left_out_id, name="Arroz")
        ],
        warnings=["2 food(s) have no conversion to grams and were left out"],
        top_sources=[
            ReportNutrientSources(
                nutrient=PrioritizedNutrient.CALCIUM,
                foods=[
                    ReportFoodSource(
                        food_id=food_id, name="Leche", amount_per_100_kcal=180.0
                    )
                ],
            )
        ],
    )

    prompt = build_prompt(analysis)

    context = context_of(prompt)
    assert context["energy_kcal"] == 1234.5
    assert context["warnings"] == analysis.warnings
    assert context["top_sources"][0]["foods"] == [
        {"name": "Leche", "amount_per_100_kcal": 180.0}
    ]
    assert context["foods_without_conversion"] == [{"name": "Arroz"}]
    assert str(food_id) not in prompt
    assert str(left_out_id) not in prompt


def test_summary_is_returned_exactly_as_written():
    raw = summary_of(overview="  El mes estuvo equilibrado.\n\nSin cambios.  ")

    assert parse_summary(raw).model_dump() == raw


def test_sections_with_nothing_to_say_may_be_empty():
    raw = summary_of(
        at_risk_nutrients=[], macros="", gapa_groups="", incorporate="", limitations=[]
    )

    assert parse_summary(raw).at_risk_nutrients == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"overview": ""},
        {"overview": " \n\t "},
        {"at_risk_nutrients": ["Calcio: bajo.", "  "]},
        {"overview": "x" * (SUMMARY_TEXT_MAX_LENGTH + 1)},
        {"limitations": ["x" * (SUMMARY_TEXT_MAX_LENGTH + 1)]},
        {"limitations": ["Un dato."] * (SUMMARY_MAX_ITEMS + 1)},
    ],
    ids=[
        "empty-overview",
        "blank-overview",
        "blank-item",
        "overview-too-long",
        "item-too-long",
        "too-many-items",
    ],
)
def test_unusable_summary_is_rejected(overrides):
    with pytest.raises(ValidationError):
        parse_summary(summary_of(**overrides))


def test_response_schema_keeps_every_field_and_leaves_the_bounds_to_the_parser():
    sent = json.dumps(RESPONSE_SCHEMA)

    assert set(RESPONSE_SCHEMA["required"]) == set(NutritionReportSummary.model_fields)
    assert "maxLength" not in sent and "maxItems" not in sent
