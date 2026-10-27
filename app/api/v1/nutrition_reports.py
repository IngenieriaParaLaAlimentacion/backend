from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response, status

from app.api.v1.params import AUTH_RESPONSES, PaginatedQueryParams
from app.core.dependencies import (
    get_nutrition_report_generation_service,
    get_nutrition_report_service,
    require_admin_or_analyst,
)
from app.core.rate_limit import limit_by_user
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


@router.put(
    "/{establishment_id}/nutrition-reports/{month}",
    dependencies=[limit_by_user("rate_limit_ai_user", "ai")],
    response_model=NutritionReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Get or generate the monthly nutrition report of an establishment",
    description=(
        "Returns the nutrition report of the establishment for a calendar month. "
        "A report that was already generated is returned as saved, without calling "
        "the AI (200). Otherwise it is calculated, written up by the AI and saved "
        "(201). A month with no intakes is saved as no data, without calling the AI. "
        "If the AI fails, the calculated data is still saved and the summary is "
        "marked unavailable: asking again for that month writes only the summary "
        "again (200). The current month and future months are rejected (422), and "
        "a month whose foods have no known conversion to grams answers 409 and is "
        "not saved. Every call counts toward the AI quota. Accessible by admins and "
        "analysts."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_200_OK: {
            "description": "Report already saved, or its unavailable summary "
            "written again",
            "model": NutritionReportResponse,
        },
        status.HTTP_404_NOT_FOUND: {"description": "Establishment not found"},
        status.HTTP_409_CONFLICT: {
            "description": "None of the foods received in the month has a known "
            "conversion to grams"
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "The month is not over yet"
        },
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "description": "AI quota exceeded; retry after Retry-After"
        },
        status.HTTP_504_GATEWAY_TIMEOUT: {
            "description": "The request exceeded its time budget; nothing is saved"
        },
    },
)
async def put_nutrition_report(
    establishment_id: UUID,
    month: ReportMonthPath,
    response: Response,
    actor: UserActor = Depends(require_admin_or_analyst),
    service: NutritionReportService = Depends(get_nutrition_report_generation_service),
) -> NutritionReportResponse:
    """Return the report of a month, generating it first if it does not exist."""
    report, created = await service.get_or_generate_report(
        establishment_id, month, actor
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return NutritionReportResponse.model_validate(report)


@router.get(
    "/{establishment_id}/nutrition-reports/{month}/pdf",
    status_code=status.HTTP_200_OK,
    summary="Download a saved monthly nutrition report as a PDF",
    description=(
        "Returns an already generated report as a PDF file. It never generates a "
        "report or calls the AI: a month without a saved report answers 404, and a "
        "report whose AI summary is not available yet answers 409 until the summary "
        "is written again by requesting the report with the PUT route. A month "
        "without intakes is printed as it is. Accessible by admins and analysts."
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
        status.HTTP_409_CONFLICT: {
            "description": "The AI summary of the report is not available yet"
        },
    },
)
async def download_nutrition_report_pdf(
    establishment_id: UUID,
    month: ReportMonthPath,
    actor: UserActor = Depends(require_admin_or_analyst),
    service: NutritionReportService = Depends(get_nutrition_report_service),
) -> Response:
    """Return the saved report of a month as a PDF file."""
    pdf = await service.get_report_pdf(establishment_id, month, actor)
    filename = f"nutrition-report-{month}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
