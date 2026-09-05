from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from app.api.v1.exports import CSV_EXPORT_RESPONSES, csv_stream_response
from app.api.v1.params import (
    AUTH_RESPONSES,
    FoodStockListingQuery,
    PaginatedQueryParams,
)
from app.core.dependencies import get_food_stock_service, require_any
from app.domain import UserActor
from app.schemas.food_stock.food_stock_schema import FoodMovementItem, FoodStockItem
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
    "/{establishment_id}/stock/{food_id}/movements",
    response_model=PaginatedResponse[FoodMovementItem],
    summary="List the movements behind one food's balance",
    description=(
        "Intakes and outflows of a single food as one sequence, newest first, "
        "each tagged with its direction — the history that explains how the "
        "current balance got there."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Establishment or food not found"},
    },
)
async def list_food_movements(
    establishment_id: UUID,
    food_id: UUID,
    paginated: PaginatedQueryParams = Depends(),
    actor: UserActor = Depends(require_any),
    service: FoodStockService = Depends(get_food_stock_service),
) -> PaginatedResponse[FoodMovementItem]:
    result = await service.list_movements(
        establishment_id=establishment_id,
        food_id=food_id,
        actor=actor,
        page=paginated.page,
        page_size=paginated.page_size,
    )
    return PaginatedResponse[FoodMovementItem](
        items=[FoodMovementItem.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )
