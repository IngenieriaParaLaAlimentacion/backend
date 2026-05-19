import uuid
from typing import List

from pydantic import BaseModel


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
