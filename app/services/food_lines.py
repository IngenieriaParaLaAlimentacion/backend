"""Line folding shared by the services that move food in and out of stock.
"""

from decimal import Decimal
from uuid import UUID

from app.schemas.food_intakes.food_intake_schema import FoodLineRequest


def aggregate_quantities(items: list[FoodLineRequest]) -> dict[UUID, Decimal]:
    """Sum the lines per food, leaving one entry per referenced food."""
    totals: dict[UUID, Decimal] = {}
    for item in items:
        totals[item.food_id] = totals.get(item.food_id, Decimal(0)) + item.quantity
    return totals
