from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ProfileFields
from app.schemas.establishments.establishment_schema import EstablishmentResponse
from app.schemas.types import ValidStr

# -- Request --


class ProfileUpdateRequest(ProfileFields):
    """Editable profile fields. Any field other than these are rejected (422)."""

    model_config = ConfigDict(extra="forbid")

    name: ValidStr | None = None
    last_name: ValidStr | None = None


class EstablishmentIdsRequest(BaseModel):
    """A non-empty list of establishment ids to act on."""

    establishment_ids: Annotated[list[UUID], Field(min_length=1)]


# -- Response --


class EstablishmentWithStatusResponse(EstablishmentResponse):
    status: str


class ProfileResponse(ProfileFields):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    name: str
    last_name: str
    role: str
    establishments: list[EstablishmentWithStatusResponse] | None = None
