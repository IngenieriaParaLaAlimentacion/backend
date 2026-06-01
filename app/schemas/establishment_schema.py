import uuid
from typing import Annotated, List

from pydantic import BaseModel, StringConstraints, model_validator

ValidNameStr = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=100),
]


class EstablishmentRequest(BaseModel):
    name: ValidNameStr
    address: ValidNameStr


class EstablishmentUpdateRequest(BaseModel):
    name: ValidNameStr | None = None
    address: ValidNameStr | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> "EstablishmentUpdateRequest":
        if self.name is None and self.address is None:
            raise ValueError("At least one of 'name' or 'address' must be provided.")
        return self


class EstablishmentResponse(BaseModel):
    id: uuid.UUID
    name: str
    address: str

    model_config = {"from_attributes": True}


class PaginatedEstablishmentsResponse(BaseModel):
    items: List[EstablishmentResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
