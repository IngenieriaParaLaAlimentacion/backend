from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, StringConstraints, field_validator

_NameField = Annotated[str, StringConstraints(strict=True, min_length=1)]
_LocalityField = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=100)
]
_DescriptionField = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=500)
]
_PhoneField = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=20,
        pattern=r"^[0-9+\-\s()]+$",
    ),
]


class RegisterFieldWorkerRequest(BaseModel):
    email: EmailStr
    password: str
    name: _NameField
    last_name: _NameField
    establishments: Annotated[list[UUID], Field(min_length=1)]
    locality: _LocalityField | None = None
    description: _DescriptionField | None = None
    contact_phone: _PhoneField | None = None

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
    locality: str | None = None
    description: str | None = None
    contact_phone: str | None = None

    model_config = {"from_attributes": True}


class UserInTokenResponse(BaseModel):
    id: UUID
    email: str
    name: str
    last_name: str
    role: str

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserInTokenResponse


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    device_id: UUID


class LogoutRequest(BaseModel):
    device_id: str
    refresh_token: str


class RefreshRequest(BaseModel):
    refresh_token: str
    device_id: UUID


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class PasswordRecoveryRequest(BaseModel):
    email: EmailStr


class PasswordRecoveryConfirmRequest(BaseModel):
    token: Annotated[str, StringConstraints(strict=True, min_length=1)]
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v
