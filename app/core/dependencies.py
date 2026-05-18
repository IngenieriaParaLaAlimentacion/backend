from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

from app.core.security import decode_token
from app.models.user import UserActor

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(token: str = Depends(oauth2_scheme)) -> UserActor:
    """Validate a user access token and return the authenticated actor."""
    payload = decode_token(token, expected_role="user")
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return UserActor(user_id=payload["sub"], role=payload["role"])


async def get_current_admin(token: str = Depends(oauth2_scheme)) -> UserActor:
    """Validate an admin access token and return the authenticated actor."""
    payload = decode_token(token, expected_role="admin")
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return UserActor(user_id=payload["sub"], role=payload["role"])


async def get_current_professional(token: str = Depends(oauth2_scheme)) -> UserActor:
    """Validate a professional access token and return the authenticated actor."""
    payload = decode_token(token, expected_role="professional")
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
