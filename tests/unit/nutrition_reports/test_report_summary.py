import json
import uuid

import pytest
from pydantic import ValidationError

from app.domain.nutrition import GapaGroup, Macronutrient, PrioritizedNutrient
from app.domain.nutrition_report import SUMMARY_TEXT_MAX_LENGTH
from app.schemas.nutrition_reports.nutrition_report_schema import (
    NutritionReportAnalysis,
    NutritionReportSummary,
    ReportFoodSource,
    ReportFoodWithoutConversion,
    ReportGapaGroup,
    ReportLimit,
    ReportMacro,
    ReportNutrient,
    ReportNutrientSources,
)
from app.services.llm.structured_schema import structured_schema
from app.services.nutrition_reports.summary import (
    PROMPT,
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
        "conclusion": "Conviene empezar por el calcio.",
        "limitations": [],
        **overrides,
    }


def context_of(prompt: str) -> dict:
    return json.loads(prompt.split("Context:\n")[1])


def test_prompt_names_nutrients_macros_and_groups_instead_of_giving_their_codes():
    analysis = NutritionReportAnalysis(
        energy_kcal=1000.0,
        nutrients=[
            ReportNutrient(
                nutrient=PrioritizedNutrient.VITAMIN_B12,
                amount_per_1000_kcal=1.0,
                reference_per_1000_kcal=2.0,
                minimum_per_1000_kcal=1.3,
                adequacy_percent=50.0,
                adequacy_capped_percent=50.0,
                at_risk=True,
            )
        ],
        macros=[
            ReportMacro(
                macro=Macronutrient.PROTEIN,
                energy_share_percent=10.0,
                min_percent=10.0,
                max_percent=15.0,
                in_range=True,
            )
        ],
        gapa_groups=[
            ReportGapaGroup(
                group=GapaGroup.DAIRY, energy_share_percent=0.0, missing=True
            )
        ],
        limits=[ReportLimit(code="sodio", amount_per_1000_kcal=900.0)],
        top_sources=[
            ReportNutrientSources(
                nutrient=PrioritizedNutrient.VITAMIN_B12,
                foods=[
                    ReportFoodSource(
                        food_id=uuid.uuid4(), name="Hígado", amount_per_100_kcal=49.0
                    )
                ],
            )
        ],
    )

    prompt = build_prompt(analysis)

    context = context_of(prompt)
    assert context["nutrients"][0]["name"] == "Vitamina B-12"
    assert context["nutrients"][0]["unit"] == "µg"
    assert context["macros"][0]["name"] == "Proteínas"
    assert context["gapa_groups"][0]["name"] == "Leche, yogur y quesos"
    assert context["limits"][0]["name"] == "Sodio"
    assert context["top_sources"][0]["name"] == "Vitamina B-12"
    for code in ("vitamina_b12", "proteinas", "leche_yogur_y_quesos", "sodio"):
        assert code not in prompt.split("Context:\n")[1]


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
        {"conclusion": "x" * (SUMMARY_TEXT_MAX_LENGTH + 1)},
        {"at_risk_nutrients": ["Calcio: bajo."] * (len(PrioritizedNutrient) + 1)},
    ],
    ids=[
        "empty-overview",
        "blank-overview",
        "blank-item",
        "overview-too-long",
        "item-too-long",
        "conclusion-too-long",
        "more-at-risk-items-than-nutrients",
    ],
)
def test_unusable_summary_is_rejected(overrides):
    with pytest.raises(ValidationError):
        parse_summary(summary_of(**overrides))


def test_every_data_gap_can_be_listed_however_many_there_are():
    # One limitation is written per food left out, and there is no fixed number.
    limitations = [f"Alimento {number} sin conversión." for number in range(30)]

    assert parse_summary(summary_of(limitations=limitations)).limitations == limitations


def test_response_schema_keeps_every_field_and_leaves_the_bounds_to_the_parser():
    sent = json.dumps(RESPONSE_SCHEMA)

    assert set(RESPONSE_SCHEMA["properties"]) == set(
        NutritionReportSummary.model_fields
    )
    assert "maxLength" not in sent and "maxItems" not in sent


def test_the_ai_must_write_every_field_including_the_conclusion():
    # The client closes the schema, which makes every property required.
    required = structured_schema(RESPONSE_SCHEMA)["required"]

    assert set(required) == set(NutritionReportSummary.model_fields)


@pytest.mark.parametrize("field", list(NutritionReportSummary.model_fields))
def test_prompt_asks_for_every_field_of_the_summary(field):
    assert f"- {field}:" in PROMPT
