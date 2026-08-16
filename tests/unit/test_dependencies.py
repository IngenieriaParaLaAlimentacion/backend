from unittest.mock import patch
from uuid import uuid4

import pytest
from jose import JWTError

from app.core.dependencies import (
    require_admin,
    require_admin_or_analyst,
    require_any,
)
from app.exceptions.domain_exceptions import ForbiddenError, UnauthorizedError
from app.models.auth.user import UserRole

# --- require_admin_or_superadmin ---


@pytest.mark.asyncio
async def test_require_admin_or_superadmin_valid_token():
    user_id = str(uuid4())
    payload = {"sub": user_id, "role": UserRole.ADMIN}
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims",
        return_value={"role": UserRole.ADMIN},
    ):
        with patch("app.core.dependencies.decode_token", return_value=payload):
            actor = await require_admin(token="anytoken")
    assert str(actor.user_id) == user_id
    assert actor.role == UserRole.ADMIN


@pytest.mark.asyncio
async def test_require_admin_or_superadmin_invalid_signature_raises_401():
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims",
        return_value={"role": UserRole.ADMIN},
    ):
        with patch("app.core.dependencies.decode_token", return_value=None):
            with pytest.raises(UnauthorizedError):
                await require_admin(token="anytoken")


@pytest.mark.asyncio
async def test_require_admin_or_superadmin_malformed_token_raises_401():
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims", side_effect=JWTError()
    ):
        with pytest.raises(UnauthorizedError):
            await require_admin(token="notajwt")


@pytest.mark.asyncio
async def test_require_admin_or_superadmin_wrong_role_raises_403():
    payload = {"sub": str(uuid4()), "role": UserRole.FIELD_WORKER}
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims",
        return_value={"role": UserRole.FIELD_WORKER},
    ):
        with patch("app.core.dependencies.decode_token", return_value=payload):
            with pytest.raises(ForbiddenError):
                await require_admin(token="anytoken")


# --- require_admin_analyst_or_superadmin ---


@pytest.mark.asyncio
async def test_require_admin_analyst_or_superadmin_valid_token():
    user_id = str(uuid4())
    payload = {"sub": user_id, "role": UserRole.ANALYST}
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims",
        return_value={"role": UserRole.ANALYST},
    ):
        with patch("app.core.dependencies.decode_token", return_value=payload):
            actor = await require_admin_or_analyst(token="anytoken")
    assert str(actor.user_id) == user_id
    assert actor.role == UserRole.ANALYST


@pytest.mark.asyncio
async def test_require_admin_analyst_or_superadmin_invalid_signature_raises_401():
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims",
        return_value={"role": UserRole.ANALYST},
    ):
        with patch("app.core.dependencies.decode_token", return_value=None):
            with pytest.raises(UnauthorizedError):
                await require_admin_or_analyst(token="anytoken")


@pytest.mark.asyncio
async def test_require_admin_analyst_or_superadmin_wrong_role_raises_403():
    payload = {"sub": str(uuid4()), "role": UserRole.FIELD_WORKER}
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims",
        return_value={"role": UserRole.FIELD_WORKER},
    ):
        with patch("app.core.dependencies.decode_token", return_value=payload):
            with pytest.raises(ForbiddenError):
                await require_admin_or_analyst(token="anytoken")


# --- require_any ---


@pytest.mark.asyncio
async def test_require_any_valid_token_any_role():
    user_id = str(uuid4())
    payload = {"sub": user_id, "role": UserRole.FIELD_WORKER}
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims",
        return_value={"role": UserRole.FIELD_WORKER},
    ):
        with patch("app.core.dependencies.decode_token", return_value=payload):
            actor = await require_any(token="anytoken")
    assert str(actor.user_id) == user_id
    assert actor.role == UserRole.FIELD_WORKER


@pytest.mark.asyncio
async def test_require_any_malformed_token_raises_401():
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims", side_effect=JWTError()
    ):
        with pytest.raises(UnauthorizedError):
            await require_any(token="notajwt")


@pytest.mark.asyncio
async def test_require_any_invalid_signature_raises_401():
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims",
        return_value={"role": UserRole.ADMIN},
    ):
        with patch("app.core.dependencies.decode_token", return_value=None):
            with pytest.raises(UnauthorizedError):
                await require_any(token="anytoken")
