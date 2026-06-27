from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class EstablishmentWithStatusResponse(BaseModel):
    id: UUID
    name: str
    formatted_address: str
    latitude: float
    longitude: float
    place_id: str
    city: str
    province: str
    status: str

    model_config = {"from_attributes": True}


class ProfileResponse(BaseModel):
    id: UUID
    email: str
    name: str
    last_name: str
    role: str
    establishments: list[EstablishmentWithStatusResponse] | None = None

    model_config = {"from_attributes": True}


class ProfileUpdateRequest(BaseModel):
    """Editable profile fields. Any field other than these is rejected (422)."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strict=True, min_length=1)] | None = None
    last_name: Annotated[str, StringConstraints(strict=True, min_length=1)] | None = (
        None
    )


class EstablishmentAccessRequest(BaseModel):
    """Establishment ids a field worker wants to request access to."""

    establishment_ids: Annotated[list[UUID], Field(min_length=1)]
