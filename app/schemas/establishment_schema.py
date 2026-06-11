import uuid
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

ValidStr = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=100),
]

Coordinate = Annotated[float, Field(ge=-180, le=180)]


class EstablishmentRequest(BaseModel):
    name: ValidStr
    formatted_address: ValidStr
    latitude: Coordinate
    longitude: Coordinate
    place_id: ValidStr
    city: ValidStr
    province: ValidStr


class EstablishmentUpdateRequest(BaseModel):
    name: ValidStr | None = None
    formatted_address: ValidStr | None = None
    latitude: Coordinate | None = None
    longitude: Coordinate | None = None
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


class EstablishmentResponse(BaseModel):
    id: uuid.UUID
    name: str
    formatted_address: str
    latitude: float
    longitude: float
    place_id: str
    city: str
    province: str

    model_config = {"from_attributes": True}
