from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.food_intake import FoodIntakeSource
from app.schemas.food_intakes.food_intake_schema import FoodLineResponse
from app.schemas.measurements.measurement_schema import EstablishmentRefResponse

# -- Response --


class FoodMovementListItem(BaseModel):
    """A food intake or outflow row for the activity-feed view.

    One schema serves both directions: the repository normalizes
    ``food_intakes.received_at`` and ``food_outflows.occurred_at`` to a single
    ``occurred_at``, and the two source enums have identical members
    (``FoodOutflowSource`` validates through ``FoodIntakeSource`` because
    Pydantic coerces a ``str``-mixin enum by value). Which direction a row is
    comes from the item's ``type`` and from which sibling key of
    ``ActivityItemResponse`` is populated.

    No responsible reference: ``/me/activity`` is already scoped to the caller
    (same reasoning as ``SurveyResponseListItemDomain``).

    ``items`` is rendered exactly as stored, duplicate food lines included: the
    read path never aggregates. ``aggregate_quantities`` is a stock-update
    helper and must not be used here.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    occurred_at: datetime
    establishment: EstablishmentRefResponse
    source: FoodIntakeSource
    comments: str | None
    items: list[FoodLineResponse]
