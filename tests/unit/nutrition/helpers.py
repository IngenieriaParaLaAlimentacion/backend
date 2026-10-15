import csv
import uuid
from pathlib import Path

from app.domain.nutrition import FoodComposition, GapaGroup

REFERENCE_DATA = Path(__file__).parents[3] / "app" / "reference_data"


def composition(
    per_100g: dict[str, float], group: GapaGroup | None = None
) -> FoodComposition:
    """A catalog food with the given nutrients per 100 g and an optional group."""
    return FoodComposition(food_id=uuid.uuid4(), gapa_group=group, per_100g=per_100g)


def read_reference_csv(name: str) -> list[dict]:
    """The rows of a CSV in ``app/reference_data``."""
    with open(REFERENCE_DATA / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
