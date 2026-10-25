from collections.abc import Iterable
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from app.domain.food_catalog import MeasurementUnit
from app.models.food_catalog.food import Food


class GramsConverter(Protocol):
    """Converts a food's quantity between its ``base_unit`` and grams.

    ``None`` means the food has no reviewed conversion.
    """

    def to_grams(self, food_id: UUID, quantity: Decimal) -> float | None:
        """Return the grams that ``quantity`` of the food's base unit weighs."""
        ...

    def from_grams(self, food_id: UUID, grams: float) -> Decimal | None:
        """Return ``grams`` of the food expressed in its base unit."""
        ...


class CatalogGramsConverter:
    """Convert stocked foods using kilograms or reviewed per-food unit masses."""

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
