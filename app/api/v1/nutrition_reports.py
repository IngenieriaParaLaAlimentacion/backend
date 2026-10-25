from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, status

from app.api.v1.params import AUTH_RESPONSES
from app.core.dependencies import get_nutrition_report_service, require_admin_or_analyst
from app.domain import UserActor
from app.schemas.nutrition.nutrition_report_schema import NutritionReportResponse
from app.services.nutrition.nutrition_report_service import NutritionReportService

router = APIRouter(prefix="/establishments")

ReportMonthPath = Annotated[
    str,
    Path(
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description="Calendar month of the report, formatted as `YYYY-MM`.",
        examples=["2026-09"],
    ),
]


@router.get(
    "/{establishment_id}/nutrition-report/{month}",
    response_model=NutritionReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Get the saved monthly nutrition report of an establishment",
    description=(
        "Returns the report already generated for a calendar month. It never "
        "generates a report or calls the AI: a month without a saved report "
        "answers 404. Accessible by admins and analysts."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {
            "description": "Establishment not found, or no report for that month"
        },
    },
)
async def get_nutrition_report(
    establishment_id: UUID,
    month: ReportMonthPath,
    actor: UserActor = Depends(require_admin_or_analyst),
    service: NutritionReportService = Depends(get_nutrition_report_service),
) -> NutritionReportResponse:
    """Return the saved report of a month."""
    report = await service.get_report(establishment_id, month, actor)
    return NutritionReportResponse.model_validate(report)
