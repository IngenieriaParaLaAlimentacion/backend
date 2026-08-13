from collections.abc import AsyncGenerator

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from app.core.security import decode_token
from app.db.unit_of_work import UnitOfWork
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import ForbiddenError, UnauthorizedError
from app.services.activity_service import ActivityService
from app.services.admin_service import AdminService
from app.services.analytics_service import AnalyticsService
from app.services.auth.auth_service import AuthService
from app.services.auth.user_service import UserService
from app.services.establishments.establishment_dashboard_service import (
    EstablishmentDashboardService,
)
from app.services.establishments.establishment_service import EstablishmentService
from app.services.measurements.measurement_service import MeasurementService
from app.services.subjects.subject_service import SubjectService
from app.services.surveys.survey_response_service import SurveyResponseService
from app.services.surveys.survey_service import SurveyService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login", auto_error=False
)


async def get_admin_service() -> AsyncGenerator[AdminService, None]:
    """Provide an AdminService backed by a fresh UnitOfWork."""
    async with UnitOfWork() as uow:
        auth_service = AuthService(uow)
        yield AdminService(uow, auth_service)


async def get_establishment_service() -> AsyncGenerator[EstablishmentService, None]:
    """Provide an EstablishmentService backed by a fresh UnitOfWork."""
    async with UnitOfWork() as uow:
        yield EstablishmentService(uow)


async def get_auth_service() -> AsyncGenerator[AuthService, None]:
    """Provide an AuthService backed by a fresh UnitOfWork."""
    async with UnitOfWork() as uow:
        yield AuthService(uow)


async def get_subject_service() -> AsyncGenerator[SubjectService, None]:
    """Provide a SubjectService backed by a fresh UnitOfWork."""
    async with UnitOfWork() as uow:
        yield SubjectService(uow)


async def get_measurement_service() -> AsyncGenerator[MeasurementService, None]:
    """Provide a MeasurementService backed by a fresh UnitOfWork."""
    async with UnitOfWork() as uow:
        yield MeasurementService(uow)


async def get_user_service() -> AsyncGenerator[UserService, None]:
    """Provide a UserService backed by a fresh UnitOfWork."""
    async with UnitOfWork() as uow:
        yield UserService(uow)


async def get_activity_service() -> AsyncGenerator[ActivityService, None]:
    """Provide an ActivityService backed by a fresh UnitOfWork."""
    async with UnitOfWork() as uow:
        yield ActivityService(uow)


async def get_survey_service() -> AsyncGenerator[SurveyService, None]:
    """Provide a SurveyService backed by a fresh UnitOfWork."""
    async with UnitOfWork() as uow:
        yield SurveyService(uow)


async def get_survey_response_service() -> AsyncGenerator[SurveyResponseService, None]:
    """Provide a SurveyResponseService backed by a fresh UnitOfWork."""
    async with UnitOfWork() as uow:
        yield SurveyResponseService(uow)


async def get_analytics_service() -> AsyncGenerator[AnalyticsService, None]:
    """Provide an AnalyticsService backed by a fresh UnitOfWork."""
    async with UnitOfWork() as uow:
        yield AnalyticsService(uow)


async def get_establishment_dashboard_service() -> AsyncGenerator[
    EstablishmentDashboardService, None
]:
    """Provide a DashboardService backed by a fresh UnitOfWork."""
    async with UnitOfWork() as uow:
        yield EstablishmentDashboardService(uow)


def _decode_verified_payload(token: str) -> dict:
    """Verify a JWT signature and return its payload.

    Raises UnauthorizedError if the token is malformed or has an invalid signature.
    """
    try:
        claimed_role: str = jwt.get_unverified_claims(token).get("role", "")
    except JWTError:
        raise UnauthorizedError()

    payload = decode_token(token, expected_role=claimed_role)
    if payload is None:
        raise UnauthorizedError()

    return payload


async def _get_authenticated_actor(
    token: str,
    required_roles: UserRole | set[UserRole],
) -> UserActor:
    """Validate a token and enforce one or more required roles.

    Raises ForbiddenError if the token is valid but belongs to a different role.
    """
    payload = _decode_verified_payload(token)

    allowed = (
        {required_roles} if isinstance(required_roles, UserRole) else required_roles
    )

    if payload.get("role") not in allowed:
        raise ForbiddenError()

    return UserActor(user_id=payload["sub"], role=payload["role"])


# TODO: revisar cuales de estos metodos son necesarios y cuales estan duplicados


async def get_optional_actor(
    token: str | None = Depends(oauth2_scheme_optional),
) -> UserActor | None:
    """Return the authenticated actor, or None when no token is supplied.

    Used by endpoints that are public by default but expose an authenticated-only
    mode (e.g. the establishments catalog with ``available=true``). A
    present-but-invalid token still raises UnauthorizedError.
    """
    if not token:
        return None
    return await _get_authenticated_actor(token, set(UserRole))


async def require_admin_or_superadmin(token: str = Depends(oauth2_scheme)) -> UserActor:
    return await _get_authenticated_actor(token, {UserRole.ADMIN, UserRole.SUPERADMIN})


async def require_any(token: str = Depends(oauth2_scheme)) -> UserActor:
    """Dependency that accepts any authenticated role."""
    return await _get_authenticated_actor(
        token,
        {
            UserRole.ANALYST,
            UserRole.FIELD_WORKER,
            UserRole.ADMIN,
            UserRole.SUPERADMIN,
        },
    )


async def require_admin_analyst_or_superadmin(
    token: str = Depends(oauth2_scheme),
) -> UserActor:
    """Dependency that accepts admin, analyst and superadmin roles."""
    return await _get_authenticated_actor(
        token, {UserRole.ADMIN, UserRole.ANALYST, UserRole.SUPERADMIN}
    )
