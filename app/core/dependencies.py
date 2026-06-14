from collections.abc import AsyncGenerator

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from app.core.security import decode_token
from app.db.unit_of_work import UnitOfWork
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import ForbiddenError, UnauthorizedError
from app.services.admin_service import AdminService
from app.services.auth_service import AuthService
from app.services.establishment_service import EstablishmentService
from app.services.subject_service import SubjectService
from app.services.user_service import UserService

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


async def get_user_service() -> AsyncGenerator[UserService, None]:
    """Provide a UserService backed by a fresh UnitOfWork."""
    async with UnitOfWork() as uow:
        yield UserService(uow)


def _decode_verified_payload(token: str) -> dict:
    """Verify a JWT signature and return its payload.

    Raises UnauthorizedError if the token is malformed or has an invalid signature.
    """
    try:
        claimed_role = jwt.get_unverified_claims(token).get("role")
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


async def get_current_admin(token: str = Depends(oauth2_scheme)) -> UserActor:
    return await _get_authenticated_actor(token, {UserRole.ADMIN, UserRole.SUPERADMIN})


async def get_current_manager(token: str = Depends(oauth2_scheme)) -> UserActor:
    return await _get_authenticated_actor(
        token, {UserRole.ESTABLISHMENT_MANAGER, UserRole.SUPERADMIN}
    )


async def get_current_professional(token: str = Depends(oauth2_scheme)) -> UserActor:
    return await _get_authenticated_actor(
        token, {UserRole.PROFESSIONAL, UserRole.SUPERADMIN}
    )


def require_some(*roles: UserRole):
    """Return a dependency that accepts any of the given roles.
    Used when multiple actors can send the request."""

    async def dep(token: str = Depends(oauth2_scheme)) -> UserActor:
        payload = _decode_verified_payload(token)

        if payload.get("role") not in roles:
            raise ForbiddenError()

        return UserActor(user_id=payload["sub"], role=payload["role"])

    return dep


async def require_any(token: str = Depends(oauth2_scheme)) -> UserActor:
    """Dependency that accepts any authenticated role."""
    return await _get_authenticated_actor(
        token,
        {
            UserRole.PROFESSIONAL,
            UserRole.ESTABLISHMENT_MANAGER,
            UserRole.ADMIN,
            UserRole.SUPERADMIN,
        },
    )
