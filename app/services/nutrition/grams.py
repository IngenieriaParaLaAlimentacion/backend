from collections.abc import Iterable, Mapping
from decimal import Decimal
from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.food_catalog import MeasurementUnit
from app.domain.unit_conversion import ConversionResult
from app.domain.unit_conversion import to_grams as convert_to_grams
from app.models.food_catalog.food import Food


class GramsConverter:
    """Converts quantities of catalog foods from their base unit to grams."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def to_grams(
        self,
        quantities: Mapping[UUID, Decimal],
        base_units: Mapping[UUID, MeasurementUnit],
    ) -> dict[UUID, ConversionResult]:
        """Return each food's quantity in grams, or why it could not be converted.

        ``base_units`` holds the base unit of every food in ``quantities``. The
        factors of all the foods are read in one query.
        """
        factors = await self.uow.food_equivalence_repo.get_factors_by_food_ids(
            list(quantities)
        )
        return {
            food_id: convert_to_grams(quantity, base_units[food_id], factors[food_id])
            for food_id, quantity in quantities.items()
        }


class CatalogGramsConverter:
    """Convert stocked foods using kilograms or reviewed per-food unit masses.

    Temporary adapter of the recipe recommendations, replaced by ``GramsConverter``.
    """

    def __init__(self, foods: Iterable[Food]):
        self.factors = {
            food.id: Decimal(1000)
            if food.base_unit == MeasurementUnit.KILOGRAMOS
            else food.grams_per_base_unit
            for food in foods
        }

    def to_grams(self, food_id: UUID, quantity: Decimal) -> float | None:
        """Return grams, or None when the food has no reviewed unit mass."""
        factor = self.factors.get(food_id)
        return float(quantity * factor) if factor else None

    def from_grams(self, food_id: UUID, grams: float) -> Decimal | None:
        """Return stock units, or None when the food has no reviewed unit mass."""
        factor = self.factors.get(food_id)
        return Decimal(str(grams)) / factor if factor else None
