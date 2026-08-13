from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ProfileFields
from app.schemas.types import ValidStr

# -- Request --


class ProfileUpdateRequest(ProfileFields):
    """Editable profile fields. Any field other than these are rejected (422)."""

    model_config = ConfigDict(extra="forbid")

    name: ValidStr | None = None
    last_name: ValidStr | None = None


class EstablishmentAccessRequest(BaseModel):
    """Establishment ids a field worker wants to request access to."""

    establishment_ids: Annotated[list[UUID], Field(min_length=1)]


# -- Response --


class EstablishmentWithStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    formatted_address: str
    latitude: float
    longitude: float
    place_id: str
    city: str
    province: str
    status: str


class ProfileResponse(ProfileFields):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    name: str
    last_name: str
    role: str
    establishments: list[EstablishmentWithStatusResponse] | None = None
