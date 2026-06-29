from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.types import DescriptionStr, PhoneStr, ValidStr

# -- Request --


class ProfileUpdateRequest(BaseModel):
    """Editable profile fields. Any field other than these are rejected (422)."""

    model_config = ConfigDict(extra="forbid")

    name: ValidStr | None = None
    last_name: ValidStr | None = None
    locality: ValidStr | None = None
    description: DescriptionStr | None = None
    contact_phone: PhoneStr | None = None


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


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    name: str
    last_name: str
    role: str
    establishments: list[EstablishmentWithStatusResponse] | None = None
    locality: str | None = None
    description: str | None = None
    contact_phone: str | None = None
