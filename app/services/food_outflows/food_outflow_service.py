from decimal import Decimal
from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.food_outflow import FoodOutflowDomain
from app.domain.user import UserActor
from app.exceptions.domain_exceptions import (
    FoodNotFoundError,
    InsufficientStockError,
    UniqueConstraintError,
)
from app.models.food_catalog.food import Food
from app.models.food_outflows.food_outflow import FoodOutflow
from app.models.food_outflows.food_outflow_item import FoodOutflowItem
from app.schemas.food_outflows.food_outflow_schema import FoodOutflowRequest
from app.services.access import check_establishment_access
from app.services.food_lines import aggregate_quantities


class FoodOutflowService:
    """Business logic for registering food an establishment took out of stock."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def _resolve_foods(self, food_ids: list[UUID]) -> dict[UUID, Food]:
        """Return the referenced catalog foods, keyed by id.

        Resolved up front rather than left to the foreign key: a bad reference
        must answer 404 naming the food, not surface as an integrity error. The
        rows are kept and attached to the lines, so building the response does
        not have to read them back.
        """
        rows = await self.uow.food_repo.get_by_ids(food_ids)
        found = {food.id: food for food in rows}
        for food_id in food_ids:
            if food_id not in found:
                raise FoodNotFoundError(str(food_id))
        return found

    async def _spend(
        self, establishment_id: UUID, quantities: dict[UUID, Decimal]
    ) -> None:
        """Take the whole outflow off the balance, or raise naming what is short.

        One statement decides every food: the repository's conditional update
        both checks and spends, so reading the balances first would open the
        very race that update exists to close. They are only read on the
        failure path, to say how much the establishment actually holds.
        """
        applied = await self.uow.food_stock_repo.decrease_many(
            establishment_id, quantities
        )
        short = set(quantities) - applied
        if not short:
            return

        held = await self.uow.food_stock_repo.get_many(establishment_id, short)
        # The error names one food even when several fell short. Picking the
        # lowest id keeps a given outflow failing the same way every time,
        # rather than on whichever line the plan happened to reach first.
        food_id = min(short)
        raise InsufficientStockError(
            food_id=str(food_id),
            requested=str(quantities[food_id]),
            available=str(held.get(food_id, Decimal(0))),
        )

    async def register(
        self, data: FoodOutflowRequest, actor: UserActor
    ) -> tuple[FoodOutflowDomain, bool]:
        """Idempotently register an outflow and take it off the stock.

        Returns a ``(outflow, created)`` tuple: ``created`` is False for an
        idempotent replay, which returns before touching the balance.

        A line the balance cannot cover aborts the whole outflow: the caller's
        UnitOfWork rolls back, so a half-applied outflow is never left behind.

        Raises:
            EstablishmentNotFoundError: establishment_id does not exist.
            EstablishmentAccessDeniedError: field worker lacks approved access.
            FoodNotFoundError: a line references a food that does not exist.
            InsufficientStockError: a line exceeds the food's current balance.
        """
        if data.id is not None:
            existing = await self.uow.food_outflow_repo.get_by_id(data.id)
            if existing is not None:
                return FoodOutflowDomain.from_db(existing), False

        await self.uow.establishment_repo.get_by_id_or_raise(data.establishment_id)
        await check_establishment_access(self.uow, actor, data.establishment_id)
        foods = await self._resolve_foods([item.food_id for item in data.items])

        outflow = FoodOutflow(
            id=data.id,
            establishment_id=data.establishment_id,
            responsible_id=actor.user_id,
            occurred_at=data.occurred_at,
            comments=data.comments,
            source=data.source,
        )

        outflow.items = [
            FoodOutflowItem(food=foods[item.food_id], quantity=item.quantity)
            for item in data.items
        ]

        try:
            await self.uow.food_outflow_repo.create(outflow)
        except UniqueConstraintError:
            # Concurrent insert of the same id (race) -> treat as replay.
            if data.id is not None:
                raced = await self.uow.food_outflow_repo.get_by_id(data.id)
                if raced is not None:
                    return FoodOutflowDomain.from_db(raced), False
            raise

        await self._spend(data.establishment_id, aggregate_quantities(data.items))

        await self.uow.commit()
        return FoodOutflowDomain.from_db(outflow), True
