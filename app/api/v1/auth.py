from fastapi import APIRouter, Depends, Response, status

from app.core.dependencies import get_auth_service
from app.schemas.auth_schema import (
    LoginRequest,
    LogoutRequest,
    PasswordRecoveryConfirmRequest,
    PasswordRecoveryRequest,
    RefreshRequest,
    RefreshResponse,
    RegisterFieldWorkerRequest,
    RegistrationResponse,
    TokenResponse,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth")


@router.post(
    "/register/field-worker",
    response_model=RegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register field worker",
    description="Creates a new field worker account pending admin approval.",
    responses={
        status.HTTP_201_CREATED: {"description": "User registered successfully"},
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid data"},
        status.HTTP_409_CONFLICT: {"description": "User already exists"},
        status.HTTP_404_NOT_FOUND: {"description": "Establishments not found"},
    },
)
async def register_field_worker(
    data: RegisterFieldWorkerRequest, service: AuthService = Depends(get_auth_service)
) -> RegistrationResponse:
    user = await service.register_field_worker(data)
    return RegistrationResponse.model_validate(user)


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
async def login(
    data: LoginRequest, service: AuthService = Depends(get_auth_service)
) -> TokenResponse:
    result = await service.login(data)
    return TokenResponse.model_validate(result)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Logout user",
    description="Revokes a refresh token for a specific device.",
    responses={
        status.HTTP_204_NO_CONTENT: {"description": "User logged out successfully"},
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Invalid or expired refresh token"
        },
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid request payload"},
    },
)
async def logout(
    data: LogoutRequest, service: AuthService = Depends(get_auth_service)
) -> Response:
    """Logout a user by revoking the provided refresh token for the device.

    Args:
        data: Logout payload with refresh token and device data.
        service: Injected authentication service.
    """

    await service.logout(data)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/refresh",
    response_model=RefreshResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh authentication tokens",
    description="Rotates the refresh token and issues a new access token.",
    responses={
        status.HTTP_200_OK: {"description": "Tokens refreshed successfully"},
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Invalid or expired refresh token"
        },
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid request payload"},
    },
)
async def refresh(
    data: RefreshRequest, service: AuthService = Depends(get_auth_service)
) -> RefreshResponse:
    result = await service.refresh(data)
    return RefreshResponse.model_validate(result)


@router.post(
    "/password-recovery/request",
    status_code=status.HTTP_202_ACCEPTED,
    response_class=Response,
    summary="Request password recovery",
    description="Creates a one-time recovery token and sends a deep link by email.",
    responses={
        status.HTTP_202_ACCEPTED: {
            "description": (
                "Request accepted. If the email exists, recovery instructions are sent."
            )
        },
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid request payload"},
    },
)
async def request_password_recovery(
    data: PasswordRecoveryRequest, service: AuthService = Depends(get_auth_service)
) -> Response:
    """Request password recovery for a user email."""
    await service.request_password_recovery(data)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post(
    "/password-recovery/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Confirm password recovery",
    description="Consumes a valid recovery token and updates the user's password.",
    responses={
        status.HTTP_204_NO_CONTENT: {"description": "Password updated successfully"},
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Invalid or expired recovery token"
        },
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid request payload"},
    },
)
async def confirm_password_recovery(
    data: PasswordRecoveryConfirmRequest,
    service: AuthService = Depends(get_auth_service),
) -> Response:
    """Confirm password recovery and set a new password."""

    await service.confirm_password_recovery(data)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
