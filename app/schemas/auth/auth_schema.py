from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
)

from app.schemas.common import ProfileFields
from app.schemas.types import PasswordStr, ValidStr

# -- Request --


class RegisterFieldWorkerRequest(ProfileFields):
    email: EmailStr
    password: PasswordStr
    name: ValidStr
    last_name: ValidStr
    establishments: list[UUID] = Field(
        default_factory=list,
        description="Establishments the field worker requests access to. "
        "Optional: account access does not depend on them.",
    )


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
    new_password: PasswordStr


class VerifyEmailRequest(BaseModel):
    token: Annotated[str, StringConstraints(strict=True, min_length=1)]


class ResendVerificationRequest(BaseModel):
    email: EmailStr


# -- Response --


class RegistrationResponse(ProfileFields):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    name: str
    last_name: str
    role: str
    status: str
    establishments: list[UUID]


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
