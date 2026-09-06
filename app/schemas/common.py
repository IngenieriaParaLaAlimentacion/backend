from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.types import DescriptionStr, PhoneStr, ValidStr


class IdentifierRefSchema(BaseModel):
    """Base schema for resources that expose id and name."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


class ProfileFields(BaseModel):
    """Editable profile fields shared by requests and responses."""

    locality: ValidStr | None = None
    description: DescriptionStr | None = None
    contact_phone: PhoneStr | None = None
