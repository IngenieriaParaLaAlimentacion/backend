import uuid

from app.domain.nutrition import FoodComposition, GapaGroup


def composition(
    per_100g: dict[str, float], group: GapaGroup | None = None
) -> FoodComposition:
    """A catalog food with the given nutrients per 100 g and an optional group."""
    return FoodComposition(food_id=uuid.uuid4(), gapa_group=group, per_100g=per_100g)
