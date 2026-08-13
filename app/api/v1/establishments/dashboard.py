from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.v1.params import (
    AUTH_RESPONSES,
    EstablishmentFieldWorkersQuery,
    EstablishmentSubjectsQuery,
    PaginatedQueryParams,
)
from app.core.dependencies import (
    get_establishment_dashboard_service,
    require_admin_analyst_or_superadmin,
)
from app.domain import UserActor
from app.schemas.establishment_dashboard_schema import (
    EstablishmentDashboardResponse,
    EstablishmentFieldWorkerListItem,
    EstablishmentSubjectListItem,
)
from app.schemas.pagination import PaginatedResponse
from app.services.establishments.establishment_dashboard_service import (
    EstablishmentDashboardService,
)

router = APIRouter(prefix="/establishments")


@router.get(
    "/{establishment_id}/dashboard",
    response_model=EstablishmentDashboardResponse,
    status_code=status.HTTP_200_OK,
    summary="Get aggregated metrics and alert status for an establishment",
    description=(
        "Returns the establishment's identification data, aggregated metrics "
        "(number of subjects and averages of height, weight, BMI and age) and "
        "its overall alert state. Averages are computed over each subject's most "
        "recent measurement at this establishment. When the establishment has no "
        "measurements, `has_data` is false and every average is null rather than "
        "zero. Accessible by admins and analysts."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Establishment not found"},
    },
)
async def get_establishment_dashboard(
    establishment_id: UUID,
    _: UserActor = Depends(require_admin_analyst_or_superadmin),
    service: EstablishmentDashboardService = Depends(
        get_establishment_dashboard_service
    ),
) -> EstablishmentDashboardResponse:
    dashboard = await service.get_establishment_dashboard(establishment_id)
    return EstablishmentDashboardResponse.model_validate(dashboard)


@router.get(
    "/{establishment_id}/subjects",
    response_model=PaginatedResponse[EstablishmentSubjectListItem],
    status_code=status.HTTP_200_OK,
    summary="List the subjects attending an establishment",
    description=(
        "Returns a paginated list of the subjects measured at this establishment, "
        "enriched with their latest measurement and derived anthropometric status. "
        "Supports searching by name, last name or DNI, and sorting by measurement "
        "date, name, BMI or age. Accessible by admins and analysts."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Establishment not found"},
    },
)
async def list_establishment_subjects(
    establishment_id: UUID,
    query: EstablishmentSubjectsQuery = Depends(),
    paginated: PaginatedQueryParams = Depends(),
    _: UserActor = Depends(require_admin_analyst_or_superadmin),
    service: EstablishmentDashboardService = Depends(
        get_establishment_dashboard_service
    ),
) -> PaginatedResponse[EstablishmentSubjectListItem]:
    result = await service.list_establishment_subjects(
        establishment_id=establishment_id,
        page=paginated.page,
        page_size=paginated.page_size,
        params=query.to_domain(),
    )
    return PaginatedResponse[EstablishmentSubjectListItem](
        items=[EstablishmentSubjectListItem.model_validate(i) for i in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@router.get(
    "/{establishment_id}/field-workers",
    response_model=PaginatedResponse[EstablishmentFieldWorkerListItem],
    status_code=status.HTTP_200_OK,
    summary="List the field workers enrolled at an establishment",
    description=(
        "Returns a paginated list of the users enrolled in this establishment "
        "together with how many measurements each has taken here and when they "
        "last did. Defaults to approved enrollments; use `relation_status` to see "
        "pending or rejected ones. Accessible by admins and analysts."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Establishment not found"},
    },
)
async def list_establishment_field_workers(
    establishment_id: UUID,
    query: EstablishmentFieldWorkersQuery = Depends(),
    paginated: PaginatedQueryParams = Depends(),
    _: UserActor = Depends(require_admin_analyst_or_superadmin),
    service: EstablishmentDashboardService = Depends(
        get_establishment_dashboard_service
    ),
) -> PaginatedResponse[EstablishmentFieldWorkerListItem]:
    result = await service.list_establishment_field_workers(
        establishment_id=establishment_id,
        page=paginated.page,
        page_size=paginated.page_size,
        params=query.to_domain(),
    )
    return PaginatedResponse[EstablishmentFieldWorkerListItem](
        items=[
            EstablishmentFieldWorkerListItem.model_validate(i) for i in result.items
        ],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )
