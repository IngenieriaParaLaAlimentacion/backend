import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator

from app.schemas.types import Latitude, Longitude, ValidStr

# -- Request --


class EstablishmentCreationRequestCreate(BaseModel):
    """Payload for a field worker requesting the creation of a
    missing establishment. Name and address are not optional."""

    name: ValidStr
    formatted_address: ValidStr
    city: ValidStr | None = None
    province: ValidStr | None = None


class EstablishmentRequest(BaseModel):
    name: ValidStr
    formatted_address: ValidStr
    latitude: Latitude
    longitude: Longitude
    place_id: ValidStr
    city: ValidStr
    province: ValidStr


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


class EstablishmentCreationRequestAdminView(EstablishmentCreationRequestResponse):
    """An establishment request as seen by an admin reviewing it, including
    the requesting field worker's identity."""

    requester_name: str
    requester_last_name: str
    requester_email: str
