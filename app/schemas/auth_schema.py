from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
)

from app.schemas.types import DescriptionStr, PhoneStr, ValidStr

# -- Request --


class RegisterFieldWorkerRequest(BaseModel):
    email: EmailStr
    password: str
    name: ValidStr
    last_name: ValidStr
    establishments: list[UUID] = Field(
        default_factory=list,
        description="Establishments the field worker requests access to. "
        "Optional: account access does not depend on them.",
    )
    locality: ValidStr | None = None
    description: DescriptionStr | None = None
    contact_phone: PhoneStr | None = None

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


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


class VerifyEmailRequest(BaseModel):
    token: Annotated[str, StringConstraints(strict=True, min_length=1)]


class ResendVerificationRequest(BaseModel):
    email: EmailStr


# -- Response --


class RegistrationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class UserInTokenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    name: str
    last_name: str
    role: str


class TokenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserInTokenResponse


class RefreshResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
