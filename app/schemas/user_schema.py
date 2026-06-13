from uuid import UUID

from pydantic import BaseModel


class EstablishmentWithStatusResponse(BaseModel):
    id: UUID
    name: str
    address: str
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
