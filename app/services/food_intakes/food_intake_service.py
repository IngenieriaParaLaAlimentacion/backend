from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.food_intake import FoodIntakeDomain
from app.domain.user import UserActor
from app.exceptions.domain_exceptions import FoodNotFoundError, UniqueConstraintError
from app.models.food_catalog.food import Food
from app.models.food_intakes.food_intake import FoodIntake
from app.models.food_intakes.food_intake_item import FoodIntakeItem
from app.schemas.food_intakes.food_intake_schema import FoodIntakeRequest
from app.services.access import check_establishment_access
from app.services.food_lines import aggregate_quantities


class FoodIntakeService:
    """Business logic for registering food an establishment received."""

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

    async def register(
        self, data: FoodIntakeRequest, actor: UserActor
    ) -> tuple[FoodIntakeDomain, bool]:
        """Idempotently register an intake and add it to the establishment's stock.

        Returns a ``(intake, created)`` tuple: ``created`` is True for a brand-new
        intake (201) and False for an idempotent replay of an existing id (200).
        A replay returns before touching the balance — applying a re-sent intake
        twice would inflate the stock with no trace of why.

        Raises:
            EstablishmentNotFoundError: establishment_id does not exist.
            EstablishmentAccessDeniedError: field worker lacks approved access.
            FoodNotFoundError: a line references a food that does not exist.
        """
        if data.id is not None:
            existing = await self.uow.food_intake_repo.get_by_id(data.id)
            if existing is not None:
                return FoodIntakeDomain.from_db(existing), False

        await self.uow.establishment_repo.get_by_id_or_raise(data.establishment_id)
        await check_establishment_access(self.uow, actor, data.establishment_id)
        foods = await self._resolve_foods([item.food_id for item in data.items])

        intake = FoodIntake(
            id=data.id,
            establishment_id=data.establishment_id,
            responsible_id=actor.user_id,
            received_at=data.received_at,
            comments=data.comments,
            source=data.source,
            photo_key=data.photo_key,
        )
        intake.items = [
            FoodIntakeItem(food=foods[item.food_id], quantity=item.quantity)
            for item in data.items
        ]

        try:
            await self.uow.food_intake_repo.create(intake)
        except UniqueConstraintError:
            # Concurrent insert of the same id (race) -> treat as replay.
            if data.id is not None:
                raced = await self.uow.food_intake_repo.get_by_id(data.id)
                if raced is not None:
                    return FoodIntakeDomain.from_db(raced), False
            raise

        await self.uow.food_stock_repo.increase_batch(
            establishment_id=data.establishment_id,
            quantities=aggregate_quantities(data.items),
        )

        await self.uow.commit()
        return FoodIntakeDomain.from_db(intake), True
