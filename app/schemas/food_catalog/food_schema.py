from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.food_catalog import MeasurementUnit, NutrientGroup
from app.schemas.common import IdentifierRefSchema


class FoodCategoryRefResponse(IdentifierRefSchema):
    pass


class FoodListItem(BaseModel):
    """A summarized food row for the catalog listing view."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    base_unit: MeasurementUnit
    category: FoodCategoryRefResponse


class NutrientRefResponse(BaseModel):
    """A nutrient's own definition, as referenced from a food's composition."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    unit: str
    group: NutrientGroup


class FoodNutrientValueItem(BaseModel):
    """A single (food, nutrient) reading in a food's detail view."""

    model_config = ConfigDict(from_attributes=True)

    nutrient: NutrientRefResponse
    amount_per_100g: Decimal


class FoodDetailResponse(FoodListItem):
    """A food's full detail, including its nutrient composition."""

    nutrients: list[FoodNutrientValueItem]
