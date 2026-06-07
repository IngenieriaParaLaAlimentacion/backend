import uuid
from typing import Annotated, List

from pydantic import BaseModel, StringConstraints, model_validator

ValidNameStr = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=100),
]


class EstablishmentRequest(BaseModel):
    name: ValidNameStr
    formatted_address: ValidNameStr
    latitude: float
    longitude: float
    place_id: str
    city: str | None = None
    province: str | None = None


class EstablishmentUpdateRequest(BaseModel):
    name: ValidNameStr | None = None
    formatted_address: ValidNameStr | None = None
    latitude: float | None = None
    longitude: float | None = None
    place_id: str | None = None
    city: str | None = None
    province: str | None = None

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
    latitude: float | None
    longitude: float | None
    place_id: str | None
    city: str | None
    province: str | None

    model_config = {"from_attributes": True}


class PaginatedEstablishmentsResponse(BaseModel):
    items: List[EstablishmentResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
