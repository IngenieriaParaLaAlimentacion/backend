from dataclasses import dataclass
from decimal import Decimal
from enum import Enum, StrEnum
from typing import NamedTuple
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
    """Sort orders accepted by the food catalog and food category listings."""

    NAME_ASC = "name_asc"
    NAME_DESC = "name_desc"


@dataclass
class FoodListingParams:
    """Query parameters for a paginated food catalog listing."""

    search: str | None = None
    category_id: UUID | None = None
    sort_order: FoodSortOrder = FoodSortOrder.NAME_ASC

    def __post_init__(self) -> None:
        self.search = normalize_optional_str(self.search)


@dataclass
class FoodCategoryListingParams:
    """Query parameters for the food category listing."""

    sort_order: FoodSortOrder = FoodSortOrder.NAME_ASC


@dataclass
class FoodListItemDomain:
    """A summarized food row for the catalog listing view."""

    id: UUID
    code: str
    name: str
    base_unit: MeasurementUnit
    category: IdentifierRefDomain

    @classmethod
    def from_db(cls, food) -> "FoodListItemDomain":
        """Build a list item from a food row with ``category`` loaded."""
        return cls(
            id=food.id,
            code=food.code,
            name=food.name,
            base_unit=food.base_unit,
            category=IdentifierRefDomain.from_db(food.category),
        )


@dataclass
class NutrientRefDomain:
    """A nutrient's own definition, as referenced from a food's composition."""

    id: UUID
    name: str
    unit: str
    group: NutrientGroup

    @classmethod
    def from_db(cls, nutrient) -> "NutrientRefDomain":
        return cls(
            id=nutrient.id,
            name=nutrient.name,
            unit=nutrient.unit,
            group=nutrient.group,
        )


@dataclass
class FoodNutrientValueDomain:
    """A single (food, nutrient) reading, as returned in a food's detail view."""

    nutrient: NutrientRefDomain
    amount_per_100g: Decimal

    @classmethod
    def from_db(cls, value) -> "FoodNutrientValueDomain":
        """Build from a FoodNutrientValue row with ``nutrient`` loaded."""
        return cls(
            nutrient=NutrientRefDomain.from_db(value.nutrient),
            amount_per_100g=value.amount_per_100g,
        )


class FoodNutrientRow(NamedTuple):
    """One (food, nutrient) reading with the food's GAPA group, no relations."""

    food_id: UUID
    gapa_category_code: str | None
    nutrient_code: str
    amount_per_100g: Decimal


# SARA 2's own table split: macronutrients (fatty acids as their sub-list)
# first, then vitamins/minerals — NutrientGroup's declaration order doesn't
# match this, so the order is spelled out explicitly rather than relied upon.
_NUTRIENT_GROUP_ORDER = {
    NutrientGroup.MACRONUTRIENT: 0,
    NutrientGroup.FATTY_ACID: 1,
    NutrientGroup.VITAMIN: 2,
    NutrientGroup.MINERAL: 3,
}


@dataclass
class FoodDetailDomain:
    """A food's full detail, including its nutrient composition."""

    id: UUID
    code: str
    name: str
    base_unit: MeasurementUnit
    category: IdentifierRefDomain
    nutrients: list[FoodNutrientValueDomain]

    @classmethod
    def from_db(cls, food) -> "FoodDetailDomain":
        """Build from a food row with ``category`` and ``nutrient_values``
        (each with its ``nutrient``) loaded.

        Nutrients are sorted by group then name — mirrors SARA 2's own split
        into a macronutrient table and a vitamins/minerals table, as a flat,
        client-groupable list rather than pre-nested by group.
        """
        nutrients = sorted(
            (FoodNutrientValueDomain.from_db(v) for v in food.nutrient_values),
            key=lambda v: (_NUTRIENT_GROUP_ORDER[v.nutrient.group], v.nutrient.name),
        )
        return cls(
            id=food.id,
            code=food.code,
            name=food.name,
            base_unit=food.base_unit,
            category=IdentifierRefDomain.from_db(food.category),
            nutrients=nutrients,
        )
