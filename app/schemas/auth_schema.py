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
