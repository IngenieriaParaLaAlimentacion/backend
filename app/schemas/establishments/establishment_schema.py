import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.establishment_characterization import CharacterizationStatus
from app.schemas.establishments.establishment_characterization_schema import (
    EstablishmentCharacterization,
)
from app.schemas.types import DescriptionStr, Latitude, Longitude, ValidStr

# -- Request --


class EstablishmentCreationRequestCreate(BaseModel):
    """Payload for a field worker requesting the creation of a
    missing establishment. Name and address are not optional."""

    name: ValidStr
    formatted_address: ValidStr
    city: ValidStr | None = None
    province: ValidStr | None = None
    characterization: EstablishmentCharacterization | None = Field(
        default=None,
        description="Optional characterization profile proposed for the "
        "establishment, for the admin to review on approval.",
    )


class EstablishmentRequest(BaseModel):
    name: ValidStr
    formatted_address: ValidStr
    latitude: Latitude
    longitude: Longitude
    place_id: ValidStr
    city: ValidStr
    province: ValidStr


class EstablishmentApprovalRequest(EstablishmentRequest):
    """Payload for an admin approving an establishment creation request."""

    characterization: EstablishmentCharacterization | None = Field(
        default=None,
        description="Final characterization profile. When omitted, the one "
        "sent with the request is used. A reused establishment keeps its own "
        "profile if it already holds an answer.",
    )


class EstablishmentRequestRejection(BaseModel):
    """Payload for an admin rejecting an establishment creation request."""

    reason: DescriptionStr | None = None


class EstablishmentUpdateRequest(BaseModel):
    name: ValidStr | None = None
    formatted_address: ValidStr | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    place_id: ValidStr | None = None
    city: ValidStr | None = None
    province: ValidStr | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> "EstablishmentUpdateRequest":
        if all(
            v is None
            for v in (
                self.name,
                self.formatted_address,
                self.latitude,
                self.longitude,
                self.place_id,
                self.city,
                self.province,
            )
        ):
            raise ValueError("At least one field must be provided.")
        return self


# -- Response --


class EstablishmentCreationRequestResponse(EstablishmentCreationRequestCreate):
    """An establishment creation request as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    status: str
    created_at: datetime


class EstablishmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    formatted_address: str
    latitude: float
    longitude: float
    place_id: str
    city: str
    province: str
    characterization_status: CharacterizationStatus = Field(
        description=(
            "Computed, never stored: `pending` when no characterization field "
            "holds an answer, `complete` when at least one does."
        )
    )


class EstablishmentApprovalResponse(EstablishmentResponse):
    """An establishment resolved by approving a creation request."""

    reused: bool = Field(
        description=(
            "True when this place already existed (e.g. another request "
            "for it was approved first): the field worker is linked to it "
            "as-is, and the data submitted for this approval was discarded "
            "(except the characterization profile, stored only when the "
            "establishment had none)."
        )
    )


class EstablishmentCreationRequestAdminView(EstablishmentCreationRequestResponse):
    """An establishment request as seen by an admin reviewing it, including
    the requesting field worker's identity."""

    requester_name: str
    requester_last_name: str
    requester_email: str
    reviewed_by: uuid.UUID | None
    updated_at: datetime
