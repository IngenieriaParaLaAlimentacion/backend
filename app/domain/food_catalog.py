from dataclasses import dataclass
from enum import Enum, StrEnum
from uuid import UUID

from app.domain.common_domains import IdentifierRefDomain, normalize_optional_str


class MeasurementUnit(str, Enum):
    """Unit a food's stock quantity is persisted in."""

    UNIDADES = "unidades"
    KILOGRAMOS = "kilogramos"
    LITROS = "litros"


class NutrientGroup(str, Enum):
    """Which of SARA 2's two composition tables a nutrient belongs to."""

    MACRONUTRIENT = "macronutrient"
    VITAMIN = "vitamin"
    MINERAL = "mineral"
    FATTY_ACID = "fatty_acid"


class FoodSortOrder(StrEnum):
    """Sort orders accepted by the food catalog listing."""

    NAME_ASC = "name_asc"
    NAME_DESC = "name_desc"


@dataclass
class FoodListingParams:
    """Query parameters for a paginated food catalog listing."""

    search: str | None = None
    category_id: UUID | None = None
    is_active: bool | None = True
    sort_order: FoodSortOrder = FoodSortOrder.NAME_ASC

    def __post_init__(self) -> None:
        self.search = normalize_optional_str(self.search)


@dataclass
class FoodListItemDomain:
    """A summarized food row for the catalog listing view."""

    id: UUID
    code: str
    name: str
    base_unit: MeasurementUnit
    is_active: bool
    category: IdentifierRefDomain

    @classmethod
    def from_db(cls, food) -> "FoodListItemDomain":
        """Build a list item from a food row with ``category`` loaded."""
        return cls(
            id=food.id,
            code=food.code,
            name=food.name,
            base_unit=food.base_unit,
            is_active=food.is_active,
            category=IdentifierRefDomain.from_db(food.category),
        )
