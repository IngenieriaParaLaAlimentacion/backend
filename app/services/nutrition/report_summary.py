import json
from pathlib import Path
from typing import Any

from app.schemas.nutrition.nutrition_report_schema import (
    NutritionReportAnalysis,
    NutritionReportSummary,
)
from app.services.llm.structured_schema import without_bounds

PROMPT_VERSION = "v2"
PROMPT = (
    Path(__file__).parent / "prompts" / PROMPT_VERSION / "report_summary.txt"
).read_text()

RESPONSE_SCHEMA: dict[str, Any] = without_bounds(
    NutritionReportSummary.model_json_schema()
)


def build_prompt(analysis: NutritionReportAnalysis) -> str:
    """Return the prompt asking the AI to write the summary of an analysis.

    The context holds the calculated figures and leaves out the internal ids of
    the foods.
    """
    context = analysis.model_dump(
        mode="json",
        exclude={
            "top_sources": {"__all__": {"foods": {"__all__": {"food_id"}}}},
            "foods_without_conversion": {"__all__": {"food_id"}},
        },
    )
    return PROMPT.replace("{context}", json.dumps(context, ensure_ascii=False))


def parse_summary(raw: dict[str, Any]) -> NutritionReportSummary:
    """Return the summary the AI wrote, exactly as it wrote it.

    Raises:
        ValidationError: a section is missing or over the length limit, or the
            overview or a list item is blank.
    """
    return NutritionReportSummary.model_validate(raw)
