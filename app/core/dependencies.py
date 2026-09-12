from collections.abc import AsyncGenerator

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from app.core.security import decode_token
from app.db.unit_of_work import UnitOfWork
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import (
    MissingTokenError,
    RoleNotAllowedError,
    UnauthorizedError,
)
from app.services.activity_service import ActivityService
from app.services.admin_service import AdminService
from app.services.analytics_service import AnalyticsService
from app.services.auth.auth_service import AuthService
from app.services.auth.user_service import UserService
from app.services.cloudflare_storage.r2_object_storage import R2ObjectStorage
from app.services.establishments.establishment_dashboard_service import (
    EstablishmentDashboardService,
)
from app.services.establishments.establishment_service import EstablishmentService
from app.services.food_catalog.food_service import FoodService
from app.services.food_intakes.food_intake_service import FoodIntakeService
from app.services.food_intakes.receipt_intake_service import ReceiptIntakeService
from app.services.food_outflows.food_outflow_service import FoodOutflowService
from app.services.food_stock.food_stock_service import FoodStockService
from app.services.measurements.measurement_service import MeasurementService
from app.services.subjects.subject_service import SubjectService
from app.services.surveys.survey_response_service import SurveyResponseService
from app.services.surveys.survey_service import SurveyService

# auto_error=False so a missing or non-Bearer Authorization header arrives here as
# None instead of FastAPI raising its own generic HTTPException(401) before our code
# runs. That lets us answer with the specific MissingTokenError ("auth/missing-token")
# rather than the catch-all "http-error" type, and lets one scheme serve both the
# required and the optional dependencies.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


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


async def get_food_intake_service() -> AsyncGenerator[FoodIntakeService, None]:
    """Provide a FoodIntakeService backed by a fresh UnitOfWork."""
    async with UnitOfWork() as uow:
        yield FoodIntakeService(uow)


async def get_receipt_intake_service() -> AsyncGenerator[ReceiptIntakeService, None]:
    """Provide a ReceiptIntakeService backed by a fresh UnitOfWork and R2."""
    async with UnitOfWork() as uow:
        yield ReceiptIntakeService(uow, R2ObjectStorage())


async def get_food_outflow_service() -> AsyncGenerator[FoodOutflowService, None]:
    """Provide a FoodOutflowService backed by a fresh UnitOfWork."""
    async with UnitOfWork() as uow:
        yield FoodOutflowService(uow)


async def get_food_stock_service() -> AsyncGenerator[FoodStockService, None]:
    """Provide a FoodStockService backed by a fresh UnitOfWork."""
    async with UnitOfWork() as uow:
        yield FoodStockService(uow)


async def get_food_service() -> AsyncGenerator[FoodService, None]:
    """Provide a FoodService backed by a fresh UnitOfWork."""
    async with UnitOfWork() as uow:
        yield FoodService(uow)


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
    token: str | None,
    required_roles: UserRole | set[UserRole],
) -> UserActor:
    """Validate a token and enforce one or more required roles.

    Raises MissingTokenError when no bearer token was supplied, UnauthorizedError
    when it is malformed or unverifiable, and RoleNotAllowedError when it is valid
    but belongs to a different role.
    """
    if not token:
        raise MissingTokenError()

    payload = _decode_verified_payload(token)

    allowed = (
        {required_roles} if isinstance(required_roles, UserRole) else required_roles
    )

    if payload.get("role") not in allowed:
        raise RoleNotAllowedError()

    return UserActor(user_id=payload["sub"], role=payload["role"])


async def get_optional_actor(
    token: str | None = Depends(oauth2_scheme),
) -> UserActor | None:
    """Return the authenticated actor, or None when no token is supplied.

    Used by endpoints that are public by default but expose an authenticated-only
    mode (e.g. the establishments catalog with ``available=true``). Absence of a
    token short-circuits to None before _get_authenticated_actor is reached, so its
    MissingTokenError never fires here; a present-but-invalid token still raises
    UnauthorizedError.
    """
    if not token:
        return None
    return await _get_authenticated_actor(token, set(UserRole))


async def require_admin(token: str | None = Depends(oauth2_scheme)) -> UserActor:
    return await _get_authenticated_actor(token, {UserRole.ADMIN, UserRole.SUPERADMIN})


async def require_any(token: str | None = Depends(oauth2_scheme)) -> UserActor:
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


async def require_admin_or_analyst(
    token: str | None = Depends(oauth2_scheme),
) -> UserActor:
    """Dependency that accepts admin, analyst and superadmin roles."""
    return await _get_authenticated_actor(
        token, {UserRole.ADMIN, UserRole.ANALYST, UserRole.SUPERADMIN}
    )
