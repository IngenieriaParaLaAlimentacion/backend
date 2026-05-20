from typing import Annotated, List
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.establishment_schema import EstablishmentResponse


class EstablishmentWithStatusResponse(BaseModel):
    id: UUID
    name: str
    address: str
    status: str


class UserAdminView(BaseModel):
    id: UUID
    email: str
    name: str
    last_name: str
    role: str
    status: str
    establishments: List[EstablishmentResponse]


class PaginatedUsersResponse(BaseModel):
    items: List[UserAdminView]
    total: int
    page: int
    page_size: int
    total_pages: int


class ApproveManagerRequest(BaseModel):
    approved_establishment_ids: Annotated[list[UUID], Field(min_length=1)]


class ApproveManagerResponse(BaseModel):
    id: UUID
    email: str
    name: str
    last_name: str
    role: str
    status: str
    establishments: List[EstablishmentWithStatusResponse]
