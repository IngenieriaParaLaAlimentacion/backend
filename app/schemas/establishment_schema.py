import uuid

from pydantic import BaseModel


class EstablishmentResponse(BaseModel):
    id: uuid.UUID
    name: str
    address: str

    model_config = {"from_attributes": True}
