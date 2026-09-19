from collections.abc import AsyncIterator
from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.food_stock import (
    FoodMovementDomain,
    FoodMovementListingParams,
    FoodStockItemDomain,
    FoodStockListingParams,
)
from app.domain.pagination import PaginatedResult
from app.domain.user import UserActor
from app.services.access import check_establishment_access
from app.services.exporters.csv.csv_exporter import CsvExporter


class FoodStockService:
    """Read side of the materialized per-establishment food stock."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def _resolve_establishment(self, establishment_id: UUID, actor: UserActor):
        """Confirm the establishment exists and the actor may look at it."""
        establishment = await self.uow.establishment_repo.get_by_id_or_raise(
            establishment_id
        )
        await check_establishment_access(self.uow, actor, establishment_id)
        return establishment

    async def list_stock(
        self,
        establishment_id: UUID,
        actor: UserActor,
        page: int,
        page_size: int,
        params: FoodStockListingParams,
    ) -> PaginatedResult[FoodStockItemDomain]:
        """Return a page of what the establishment currently holds.

        Raises:
            EstablishmentNotFoundError: establishment_id does not exist.
            EstablishmentAccessDeniedError: field worker lacks approved access.
        """
        await self._resolve_establishment(establishment_id, actor)
        page = max(1, page)
        rows, total = await self.uow.food_stock_repo.list_by_establishment(
            establishment_id=establishment_id,
            limit=page_size,
            offset=(page - 1) * page_size,
            params=params,
        )
        return PaginatedResult.build(
            items=[FoodStockItemDomain.from_db(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def list_movements(
        self,
        establishment_id: UUID,
        actor: UserActor,
        page: int,
        page_size: int,
        params: FoodMovementListingParams,
    ) -> PaginatedResult[FoodMovementDomain]:
        """Return a page of the establishment's movements, newest first.

        One entry per movement document -- an intake or an outflow with all its
        food lines -- not one per line.

        Raises:
            EstablishmentNotFoundError: establishment_id does not exist.
            EstablishmentAccessDeniedError: field worker lacks approved access.
        """
        await self._resolve_establishment(establishment_id, actor)
        page = max(1, page)
        movements, total = await self.uow.food_stock_repo.list_movements(
            establishment_id=establishment_id,
            limit=page_size,
            offset=(page - 1) * page_size,
            params=params,
        )
        return PaginatedResult.build(
            items=movements,
            total=total,
            page=page,
            page_size=page_size,
        )

    async def prepare_stock_export(
        self, establishment_id: UUID, actor: UserActor, params: FoodStockListingParams
    ) -> tuple[str, int]:
        """Resolve the establishment and size the export before streaming.

        Runs as a pre-flight so an unknown establishment or a denied actor
        answers a real status instead of a truncated file.
        """
        establishment = await self._resolve_establishment(establishment_id, actor)
        total = await self.uow.food_stock_repo.count_for_export(
            establishment_id, params
        )
        return establishment.name, total

    def export_stock(
        self,
        establishment_id: UUID,
        params: FoodStockListingParams,
        exporter: CsvExporter[FoodStockItemDomain],
    ) -> AsyncIterator[bytes]:
        """Stream the establishment's stock listing as an exported file's bytes.

        Not a coroutine: the caller owns the UnitOfWork for as long as the body
        streams, so this only wires the row source to the exporter.
        """
        rows = (
            FoodStockItemDomain.from_db(row)
            async for row in self.uow.food_stock_repo.stream_for_export(
                establishment_id=establishment_id, params=params
            )
        )
        return exporter.stream(rows)
