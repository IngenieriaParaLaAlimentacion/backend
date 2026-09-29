from decimal import Decimal


async def _balance(establishment_id, food_id) -> Decimal | None:
    """Read one balance straight from the table, or None if there is no row."""
    from app.db.database import AsyncSessionLocal
    from app.repositories.food_stock.food_stock_repository import FoodStockRepository

    async with AsyncSessionLocal() as session:
        held = await FoodStockRepository(session).get_many(establishment_id, [food_id])
        return held.get(food_id)


INTAKES_URL = "/api/v1/food-intakes"
OUTFLOWS_URL = "/api/v1/food-outflows"


def _intake_body(establishment_id, items, **overrides) -> dict:
    body = {
        "establishment_id": str(establishment_id),
        "occurred_at": "2026-09-01T10:00:00Z",
        "items": [
            {"food_id": str(food_id), "quantity": str(quantity)}
            for food_id, quantity in items
        ],
    }
    return {**body, **overrides}


def _outflow_body(establishment_id, items, **overrides) -> dict:
    body = {
        "establishment_id": str(establishment_id),
        "occurred_at": "2026-09-02T10:00:00Z",
        "items": [
            {"food_id": str(food_id), "quantity": str(quantity)}
            for food_id, quantity in items
        ],
    }
    return {**body, **overrides}
