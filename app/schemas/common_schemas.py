from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NamedRefResponse(BaseModel):
    # TODO: In refactor check there are some other schemas that could inherit from this
    """Base schema for resources that to expose id and name."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
