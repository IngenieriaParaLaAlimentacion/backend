from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Self
from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.food_catalog import MeasurementUnit
from app.domain.unit_conversion import (
    ConversionFactors,
    ConversionResult,
    Converted,
)
from app.domain.unit_conversion import from_grams as convert_from_grams
from app.domain.unit_conversion import to_grams as convert_to_grams
from app.models.food_catalog.food import Food


class GramsConverter:
    """Converts quantities of catalog foods from their base unit to grams.

    It answers for the foods it was loaded with, from memory.
    """

    def __init__(
        self,
        base_units: Mapping[UUID, MeasurementUnit],
        factors: Mapping[UUID, ConversionFactors],
    ) -> None:
        self.base_units = base_units
        self.factors = factors

    @classmethod
    async def load(cls, uow: IUnitOfWork, foods: Iterable[Food]) -> Self:
        """Read the factors of ``foods`` in one query and build their converter."""
        foods = list(foods)
        factors = await uow.food_equivalence_repo.get_factors_by_food_ids(
            [food.id for food in foods]
        )
        return cls({food.id: food.base_unit for food in foods}, factors)

    def convert(self, food_id: UUID, quantity: Decimal) -> ConversionResult:
        """Return the grams ``quantity`` of the food's base unit weighs, or why not.

        Raises:
            KeyError: the food was not loaded.
        """
        return convert_to_grams(
            quantity, self.base_units[food_id], self.factors[food_id]
        )

    def to_grams(self, food_id: UUID, quantity: Decimal) -> float | None:
        """Return the grams as a float for the solver, or None when not convertible.

        Raises:
            KeyError: the food was not loaded.
        """
        result = self.convert(food_id, quantity)
        return float(result.value) if isinstance(result, Converted) else None

    def from_grams(self, food_id: UUID, grams: float) -> Decimal | None:
        """Return the exact base-unit quantity of ``grams``, or None when not
        convertible.

        Raises:
            KeyError: the food was not loaded.
        """
        result = convert_from_grams(
            Decimal(str(grams)), self.base_units[food_id], self.factors[food_id]
        )
        return result.value if isinstance(result, Converted) else None


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
