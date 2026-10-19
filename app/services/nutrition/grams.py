from decimal import Decimal
from typing import Protocol
from uuid import UUID


class GramsConverter(Protocol):
    """Converts a food's quantity between its ``base_unit`` and grams.

    Placeholder for the conversion delivered by #155; the shape of its methods
    may change when that lands. ``None`` means the food has no known conversion.
    """

    def to_grams(self, food_id: UUID, quantity: Decimal) -> float | None:
        """Return the grams that ``quantity`` of the food's base unit weighs."""
        ...

    def from_grams(self, food_id: UUID, grams: float) -> Decimal | None:
        """Return ``grams`` of the food expressed in its base unit."""
        ...
