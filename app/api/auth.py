from fastapi import APIRouter, Depends, status

from app.core.dependencies import get_auth_service
from app.schemas.auth_schema import (
    LoginRequest,
    RegisterManagerRequest,
    RegistrationResponse,
    TokenResponse,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/register/establishment-manager",
    response_model=RegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register establishment manager",
    description="Creates a new establishment manager account pending admin approval.",
    responses={
        status.HTTP_201_CREATED: {"description": "User registered successfully"},
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid data"},
        status.HTTP_409_CONFLICT: {"description": "User already exists"},
        status.HTTP_404_NOT_FOUND: {"description": "Establishments not found"},
    },
)
async def register_manager(
    data: RegisterManagerRequest, service: AuthService = Depends(get_auth_service)
):
    """Register a new establishment manager."""

    return await service.register_manager(data)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login user",
    description="Authenticates a user and returns a JWT token. Blocks pending users.",
    responses={
        status.HTTP_200_OK: {"description": "Successful login"},
        status.HTTP_401_UNAUTHORIZED: {"description": "Invalid credentials"},
        status.HTTP_403_FORBIDDEN: {"description": "Account pending validation"},
    },
)
async def login(data: LoginRequest, service: AuthService = Depends(get_auth_service)):
    return await service.login(data)
