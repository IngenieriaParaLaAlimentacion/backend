from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

_LocalityField = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=100)
]
_DescriptionField = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=500)
]
_PhoneField = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=20,
        pattern=r"^[0-9+\-\s()]+$",
    ),
]


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
    locality: str | None = None
    description: str | None = None
    contact_phone: str | None = None

    model_config = {"from_attributes": True}


class ProfileUpdateRequest(BaseModel):
    """Editable profile fields. Any field other than these is rejected (422)."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strict=True, min_length=1)] | None = None
    last_name: Annotated[str, StringConstraints(strict=True, min_length=1)] | None = (
        None
    )
    locality: _LocalityField | None = None
    description: _DescriptionField | None = None
    contact_phone: _PhoneField | None = None


class EstablishmentAccessRequest(BaseModel):
    """Establishment ids a field worker wants to request access to."""

    establishment_ids: Annotated[list[UUID], Field(min_length=1)]
