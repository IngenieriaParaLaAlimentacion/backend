from collections import defaultdict
from collections.abc import Collection
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.unit_conversion import ConversionFactors
from app.models.food_catalog.food_equivalence import FoodEquivalence


class FoodEquivalenceRepository:
    """Persistence operations for FoodEquivalence entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, equivalence: FoodEquivalence) -> FoodEquivalence:
        """Stage a new food equivalence for insertion."""
        self.db.add(equivalence)
        return equivalence

    async def update(self, equivalence: FoodEquivalence) -> FoodEquivalence:
        """Persist changes made to an existing food equivalence."""
        await self.db.flush()
        return equivalence

    async def get_all(self) -> list[FoodEquivalence]:
        """Return every stored food equivalence.

        Loads the whole table, so it belongs to the seed and not to request-time
        code.
        """
        result = await self.db.execute(select(FoodEquivalence))
        return list(result.scalars().all())

    async def get_factors_by_food_ids(
        self, food_ids: Collection[UUID]
    ) -> dict[UUID, ConversionFactors]:
        """Return the conversion factors of each of these foods.

        Every requested food is in the mapping; one with no equivalence gets
        empty ``ConversionFactors``.
        """
        if not food_ids:
            return {}

        result = await self.db.execute(
            select(
                FoodEquivalence.food_id, FoodEquivalence.kind, FoodEquivalence.value
            ).where(FoodEquivalence.food_id.in_(food_ids))
        )
        values: dict[UUID, dict[str, Decimal]] = defaultdict(dict)
        for food_id, kind, value in result.all():
            # Each kind's value is named after the ConversionFactors field it fills.
            values[food_id][kind.value] = value
        return {food_id: ConversionFactors(**values[food_id]) for food_id in food_ids}
