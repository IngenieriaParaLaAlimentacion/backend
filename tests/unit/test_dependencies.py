from unittest.mock import patch
from uuid import uuid4

import pytest
from jose import JWTError

from app.core.dependencies import (
    get_current_admin,
    get_current_analyst,
    get_current_field_worker,
    require_some,
)
from app.exceptions.domain_exceptions import ForbiddenError, UnauthorizedError
from app.models.user import UserRole

# --- get_current_admin ---


@pytest.mark.asyncio
async def test_get_current_admin_valid_token():
    user_id = str(uuid4())
    payload = {"sub": user_id, "role": UserRole.ADMIN}
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims",
        return_value={"role": UserRole.ADMIN},
    ):
        with patch("app.core.dependencies.decode_token", return_value=payload):
            actor = await get_current_admin(token="anytoken")
    assert str(actor.user_id) == user_id
    assert actor.role == UserRole.ADMIN


@pytest.mark.asyncio
async def test_get_current_admin_invalid_signature_raises_401():
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims",
        return_value={"role": UserRole.ADMIN},
    ):
        with patch("app.core.dependencies.decode_token", return_value=None):
            with pytest.raises(UnauthorizedError):
                await get_current_admin(token="anytoken")


@pytest.mark.asyncio
async def test_get_current_admin_malformed_token_raises_401():
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims", side_effect=JWTError()
    ):
        with pytest.raises(UnauthorizedError):
            await get_current_admin(token="notajwt")


@pytest.mark.asyncio
async def test_get_current_admin_wrong_role_raises_403():
    payload = {"sub": str(uuid4()), "role": UserRole.FIELD_WORKER}
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims",
        return_value={"role": UserRole.FIELD_WORKER},
    ):
        with patch("app.core.dependencies.decode_token", return_value=payload):
            with pytest.raises(ForbiddenError):
                await get_current_admin(token="anytoken")


# --- get_current_field_worker ---


@pytest.mark.asyncio
async def test_get_current_field_worker_valid_token():
    user_id = str(uuid4())
    payload = {"sub": user_id, "role": UserRole.FIELD_WORKER}
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims",
        return_value={"role": UserRole.FIELD_WORKER},
    ):
        with patch("app.core.dependencies.decode_token", return_value=payload):
            actor = await get_current_field_worker(token="anytoken")
    assert str(actor.user_id) == user_id
    assert actor.role == UserRole.FIELD_WORKER


@pytest.mark.asyncio
async def test_get_current_field_worker_invalid_signature_raises_401():
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims",
        return_value={"role": UserRole.FIELD_WORKER},
    ):
        with patch("app.core.dependencies.decode_token", return_value=None):
            with pytest.raises(UnauthorizedError):
                await get_current_field_worker(token="anytoken")


@pytest.mark.asyncio
async def test_get_current_field_worker_wrong_role_raises_403():
    payload = {"sub": str(uuid4()), "role": UserRole.ADMIN}
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims",
        return_value={"role": UserRole.ADMIN},
    ):
        with patch("app.core.dependencies.decode_token", return_value=payload):
            with pytest.raises(ForbiddenError):
                await get_current_field_worker(token="anytoken")


# --- get_current_analyst ---


@pytest.mark.asyncio
async def test_get_current_analyst_valid_token():
    user_id = str(uuid4())
    payload = {"sub": user_id, "role": UserRole.ANALYST}
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims",
        return_value={"role": UserRole.ANALYST},
    ):
        with patch("app.core.dependencies.decode_token", return_value=payload):
            actor = await get_current_analyst(token="anytoken")
    assert str(actor.user_id) == user_id
    assert actor.role == UserRole.ANALYST


@pytest.mark.asyncio
async def test_get_current_analyst_invalid_signature_raises_401():
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims",
        return_value={"role": UserRole.ANALYST},
    ):
        with patch("app.core.dependencies.decode_token", return_value=None):
            with pytest.raises(UnauthorizedError):
                await get_current_analyst(token="anytoken")


@pytest.mark.asyncio
async def test_get_current_analyst_wrong_role_raises_403():
    payload = {"sub": str(uuid4()), "role": UserRole.ADMIN}
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims",
        return_value={"role": UserRole.ADMIN},
    ):
        with patch("app.core.dependencies.decode_token", return_value=payload):
            with pytest.raises(ForbiddenError):
                await get_current_analyst(token="anytoken")


# --- require_any ---


@pytest.mark.asyncio
async def test_require_any_valid_token_matching_role():
    user_id = str(uuid4())
    payload = {"sub": user_id, "role": UserRole.ADMIN}
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims",
        return_value={"role": UserRole.ADMIN},
    ):
        with patch("app.core.dependencies.decode_token", return_value=payload):
            actor = await require_some(UserRole.ADMIN, UserRole.ANALYST)(
                token="anytoken"
            )
    assert str(actor.user_id) == user_id
    assert actor.role == UserRole.ADMIN


@pytest.mark.asyncio
async def test_require_any_malformed_token_raises_401():
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims", side_effect=JWTError()
    ):
        with pytest.raises(UnauthorizedError):
            await require_some(UserRole.ADMIN, UserRole.ANALYST)(token="notajwt")


@pytest.mark.asyncio
async def test_require_any_invalid_signature_raises_401():
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims",
        return_value={"role": UserRole.ADMIN},
    ):
        with patch("app.core.dependencies.decode_token", return_value=None):
            with pytest.raises(UnauthorizedError):
                await require_some(UserRole.ADMIN, UserRole.ANALYST)(token="anytoken")


@pytest.mark.asyncio
async def test_require_any_role_not_in_allowed_raises_403():
    payload = {"sub": str(uuid4()), "role": UserRole.FIELD_WORKER}
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims",
        return_value={"role": UserRole.FIELD_WORKER},
    ):
        with patch("app.core.dependencies.decode_token", return_value=payload):
            with pytest.raises(ForbiddenError):
                await require_some(UserRole.ADMIN, UserRole.ANALYST)(token="anytoken")
