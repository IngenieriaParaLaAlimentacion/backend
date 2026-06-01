import uuid
from typing import Annotated, List

from pydantic import BaseModel, StringConstraints

ValidNameStr = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=100),
]


class EstablishmentRequest(BaseModel):
    name: ValidNameStr
    address: ValidNameStr


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
