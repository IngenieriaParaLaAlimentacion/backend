from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Response, status

from app.api.v1.params import AUTH_RESPONSES
from app.core.dependencies import get_nutrition_report_service, require_admin_or_analyst
from app.domain import UserActor
from app.schemas.nutrir.nutrition_report_schema import (
    NutritionReportListItem,
    NutritionReportResponse,
)
from app.services.nutrir.nutrition_report_service import NutritionReportService

router = APIRouter(prefix="/establishments")

ReportMonthPath = Annotated[
    str,
    Path(
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description="Calendar month of the report, formatted as `YYYY-MM`.",
        examples=["2026-09"],
    ),
]


@router.put(
    "/{establishment_id}/nutrition-report/{month}",
    response_model=NutritionReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Get or generate the monthly nutrition report of an establishment",
    description=(
        "Returns the nutrition report of the establishment for a calendar month. "
        "If the report was already generated it is returned as saved, without "
        "calling the AI again (200); otherwise it is calculated, written up by the "
        "AI and saved (201). A month with no intakes is returned as `no_data` "
        "without calling the AI. If the AI fails, the calculated data is still "
        "saved and the summary is marked as unavailable. The current month and "
        "future months are rejected. Accessible by admins and analysts."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Establishment not found"},
        status.HTTP_201_CREATED: {
            "description": "Report generated and saved",
            "model": NutritionReportResponse,
        },
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "description": "Malformed month, or a month that is not over yet"
        },
    },
)
async def put_nutrition_report(
    establishment_id: UUID,
    month: ReportMonthPath,
    response: Response,
    actor: UserActor = Depends(require_admin_or_analyst),
    service: NutritionReportService = Depends(get_nutrition_report_service),
) -> NutritionReportResponse:
    report, created = await service.get_or_generate_report(
        establishment_id, month, actor
    )
    if created:
        response.status_code = status.HTTP_201_CREATED
    return NutritionReportResponse.model_validate(report)


@router.get(
    "/{establishment_id}/nutrition-report",
    response_model=list[NutritionReportListItem],
    status_code=status.HTTP_200_OK,
    summary="List the nutrition reports already generated for an establishment",
    description=(
        "Returns the reports already generated for the establishment, most "
        "recent month first, without their analysis or summary. Accessible by "
        "admins and analysts."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Establishment not found"},
    },
)
async def list_nutrition_reports(
    establishment_id: UUID,
    actor: UserActor = Depends(require_admin_or_analyst),
    service: NutritionReportService = Depends(get_nutrition_report_service),
) -> list[NutritionReportListItem]:
    reports = await service.list_reports(establishment_id, actor)
    return [NutritionReportListItem.model_validate(report) for report in reports]


@router.get(
    "/{establishment_id}/nutrition-report/{month}/pdf",
    status_code=status.HTTP_200_OK,
    summary="Download the monthly nutrition report of an establishment as a PDF",
    description=(
        "Returns an already generated report as a PDF file. It never generates "
        "a report: a month without a saved report answers 404. Accessible by "
        "admins and analysts."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_200_OK: {
            "description": "The report as a PDF file",
            "content": {"application/pdf": {}},
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Establishment not found, or no report for that month"
        },
    },
)
async def download_nutrition_report_pdf(
    establishment_id: UUID,
    month: ReportMonthPath,
    actor: UserActor = Depends(require_admin_or_analyst),
    service: NutritionReportService = Depends(get_nutrition_report_service),
) -> Response:
    pdf = await service.get_report_pdf(establishment_id, month, actor)
    filename = f"nutrition-report-{month}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
