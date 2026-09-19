from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from app.api.v1.exports import CSV_EXPORT_RESPONSES, csv_stream_response
from app.api.v1.params import (
    AUTH_RESPONSES,
    FoodMovementListingQuery,
    FoodStockListingQuery,
    PaginatedQueryParams,
)
from app.core.dependencies import get_food_stock_service, require_any
from app.domain import UserActor
from app.schemas.food_stock.food_stock_schema import (
    FoodMovementDetail,
    FoodMovementSummary,
    FoodStockItem,
)
from app.schemas.pagination import PaginatedResponse
from app.services.exporters.csv.columns import FOOD_STOCK_EXPORTER
from app.services.food_stock.food_stock_service import FoodStockService

router = APIRouter(prefix="/establishments")

_NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"description": "Establishment not found"}}


@router.get(
    "/{establishment_id}/stock",
    response_model=PaginatedResponse[FoodStockItem],
    summary="List what an establishment currently holds",
    description=(
        "One row per food with a balance, carrying the unit from the catalog. A "
        "food that was received and then used up keeps a row at zero — never "
        "having received it and having run out are different answers. Pass "
        "`only_available=true` to see just what is on hand."
    ),
    responses={**AUTH_RESPONSES, **_NOT_FOUND},
)
async def list_establishment_stock(
    establishment_id: UUID,
    query: FoodStockListingQuery = Depends(),
    paginated: PaginatedQueryParams = Depends(),
    actor: UserActor = Depends(require_any),
    service: FoodStockService = Depends(get_food_stock_service),
) -> PaginatedResponse[FoodStockItem]:
    result = await service.list_stock(
        establishment_id=establishment_id,
        actor=actor,
        page=paginated.page,
        page_size=paginated.page_size,
        params=query.to_domain(),
    )
    return PaginatedResponse[FoodStockItem](
        items=[FoodStockItem.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@router.get(
    "/{establishment_id}/stock/export",
    summary="Export an establishment's stock as CSV",
    responses={**CSV_EXPORT_RESPONSES, **_NOT_FOUND},
)
async def export_establishment_stock(
    establishment_id: UUID,
    query: FoodStockListingQuery = Depends(),
    actor: UserActor = Depends(require_any),
    service: FoodStockService = Depends(get_food_stock_service),
) -> StreamingResponse:
    params = query.to_domain()
    # Pre-flight: resolves the establishment and sizes the export before any
    # bytes go out, so a 404 or a 403 is still expressible.
    name, total = await service.prepare_stock_export(establishment_id, actor, params)
    return csv_stream_response(
        lambda uow: FoodStockService(uow).export_stock(
            establishment_id, params, FOOD_STOCK_EXPORTER
        ),
        FOOD_STOCK_EXPORTER.filename(scope=name),
        total,
    )


@router.get(
    "/{establishment_id}/food-movements",
    response_model=PaginatedResponse[FoodMovementSummary],
    summary="List an establishment's food movements",
    description=(
        "Intakes and outflows merged into a single sequence, newest first, one "
        "entry per movement"
        "Pass `direction=in` or `direction=out` for one side only."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "`/errors/invalid-date-range`: occurred_from is "
            "after occurred_to"
        },
        **AUTH_RESPONSES,
        **_NOT_FOUND,
    },
)
async def list_establishment_movements(
    establishment_id: UUID,
    query: FoodMovementListingQuery = Depends(),
    paginated: PaginatedQueryParams = Depends(),
    actor: UserActor = Depends(require_any),
    service: FoodStockService = Depends(get_food_stock_service),
) -> PaginatedResponse[FoodMovementSummary]:
    query.validate()
    result = await service.list_movements(
        establishment_id=establishment_id,
        actor=actor,
        page=paginated.page,
        page_size=paginated.page_size,
        params=query.to_domain(),
    )
    return PaginatedResponse[FoodMovementSummary](
        items=[FoodMovementSummary.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@router.get(
    "/{establishment_id}/food-movements/{movement_id}",
    response_model=FoodMovementDetail,
    summary="Get one of an establishment's food movements",
    description=(
        "One movement — an intake or an outflow — with all of its food lines, "
        "each carrying the unit from the catalog, plus the movement's source "
        "and comments. Lines are returned as recorded: a movement that lists "
        "the same food twice comes back with both lines. A movement that "
        "belongs to another establishment answers 404, the same as one that "
        "does not exist."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {
            "description": "Establishment or movement not found"
        },
    },
)
async def get_establishment_movement(
    establishment_id: UUID,
    movement_id: UUID,
    actor: UserActor = Depends(require_any),
    service: FoodStockService = Depends(get_food_stock_service),
) -> FoodMovementDetail:
    movement = await service.get_movement(
        establishment_id=establishment_id,
        movement_id=movement_id,
        actor=actor,
    )
    return FoodMovementDetail.model_validate(movement)
