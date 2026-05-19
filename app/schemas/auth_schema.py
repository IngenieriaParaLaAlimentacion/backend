from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, StringConstraints, field_validator


class RegisterManagerRequest(BaseModel):
    email: EmailStr
    password: str
    name: Annotated[str, StringConstraints(strict=True, min_length=1)]
    last_name: Annotated[str, StringConstraints(strict=True, min_length=1)]
    establishments: Annotated[list[UUID], Field(min_length=1)]

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class RegistrationResponse(BaseModel):
    id: UUID
    email: str
    name: str
    last_name: str
    role: str
    status: str
    establishments: list[UUID]

    model_config = {"from_attributes": True}
