from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.database import get_db
from app.models.user import UserActor, UserRole
from app.repositories.establishment_repository import EstablishmentRepository
from app.services.establishment_service import EstablishmentService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_establishment_service(
    db: AsyncSession = Depends(get_db),
) -> EstablishmentService:
    """Provide an EstablishmentService with its repository wired to
    the current session."""
    return EstablishmentService(EstablishmentRepository(db))


async def get_current_manager(token: str = Depends(oauth2_scheme)) -> UserActor:
    """Validate a user access token and return the authenticated actor."""
    payload = decode_token(token, expected_role=UserRole.ESTABLISHMENT_MANAGER)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return UserActor(user_id=payload["sub"], role=payload["role"])


async def get_current_admin(token: str = Depends(oauth2_scheme)) -> UserActor:
    """Validate an admin access token and return the authenticated actor."""
    payload = decode_token(token, expected_role=UserRole.ADMIN)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return UserActor(user_id=payload["sub"], role=payload["role"])


async def get_current_professional(token: str = Depends(oauth2_scheme)) -> UserActor:
    """Validate a professional access token and return the authenticated actor."""
    payload = decode_token(token, expected_role=UserRole.PROFESSIONAL)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return UserActor(user_id=payload["sub"], role=payload["role"])


def require_any(*roles: str):
    """Return a dependency that accepts any of the given roles."""

    async def dep(token: str = Depends(oauth2_scheme)) -> UserActor:
        for role in roles:
            payload = decode_token(token, expected_role=role)
            if payload is not None:
                return UserActor(user_id=payload["sub"], role=payload["role"])
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    return dep
