from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.food_catalog import MeasurementUnit
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
    is_active: bool
    category: FoodCategoryRefResponse
