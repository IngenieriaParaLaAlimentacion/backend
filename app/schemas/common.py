from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.types import DescriptionStr, PhoneStr, ValidStr


class IdentifierRefSchema(BaseModel):
    # TODO: In refactor check there are some other schemas that could inherit from this
    """Base schema for resources that to expose id and name."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


class ProfileFields(BaseModel):
    """Editable profile fields shared by requests and responses."""

    locality: ValidStr | None = None
    description: DescriptionStr | None = None
    contact_phone: PhoneStr | None = None
