from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.v1.params import AUTH_RESPONSES, PaginatedQueryParams
from app.core.dependencies import get_nutrition_report_service, require_admin_or_analyst
from app.domain import UserActor
from app.domain.nutrition_report import NutritionReportSortOrder
from app.schemas.nutrition.nutrition_report_schema import (
    NutritionReportListItem,
    NutritionReportResponse,
)
from app.schemas.pagination import PaginatedResponse
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
    "/{establishment_id}/nutrition-reports",
    response_model=PaginatedResponse[NutritionReportListItem],
    status_code=status.HTTP_200_OK,
    summary="List the saved monthly nutrition reports of an establishment",
    description=(
        "Returns the reports already generated for the establishment, a page at a "
        "time and ordered by month: newest first, or oldest first with "
        "sort_order=month_asc. Each item has only the basics; read the full report "
        "of a month with its own route. It never generates a report or calls the "
        "AI. Accessible by admins and analysts."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Establishment not found"},
    },
)
async def list_nutrition_reports(
    establishment_id: UUID,
    sort_order: Annotated[
        NutritionReportSortOrder, Query(description="Order of the reports by month.")
    ] = NutritionReportSortOrder.MONTH_DESC,
    pagination: PaginatedQueryParams = Depends(),
    actor: UserActor = Depends(require_admin_or_analyst),
    service: NutritionReportService = Depends(get_nutrition_report_service),
) -> PaginatedResponse[NutritionReportListItem]:
    """List the saved reports of an establishment, a page at a time."""
    result = await service.list_reports(
        establishment_id,
        actor,
        sort_order=sort_order,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return PaginatedResponse[NutritionReportListItem](
        items=[NutritionReportListItem.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@router.get(
    "/{establishment_id}/nutrition-reports/{month}",
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
