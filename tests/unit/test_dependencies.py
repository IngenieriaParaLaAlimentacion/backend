from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.dependencies import (
    get_current_admin,
    get_current_manager,
    get_current_professional,
    require_any,
)
from app.models.user import UserRole


@pytest.mark.asyncio
async def test_get_current_manager_valid_token():
    user_id = str(uuid4())
    payload = {"sub": user_id, "role": UserRole.ESTABLISHMENT_MANAGER}
    with patch("app.core.dependencies.decode_token", return_value=payload):
        actor = await get_current_manager(token="faketoken")

    assert str(actor.user_id) == user_id
    assert actor.role == UserRole.ESTABLISHMENT_MANAGER


@pytest.mark.asyncio
async def test_get_current_admin_valid_token():
    user_id = str(uuid4())
    payload = {"sub": user_id, "role": UserRole.ADMIN}
    with patch("app.core.dependencies.decode_token", return_value=payload):
        actor = await get_current_admin(token="faketoken")

    assert str(actor.user_id) == user_id
    assert actor.role == UserRole.ADMIN


@pytest.mark.asyncio
async def test_get_current_professional_valid_token():
    user_id = str(uuid4())
    payload = {"sub": user_id, "role": UserRole.PROFESSIONAL}
    with patch("app.core.dependencies.decode_token", return_value=payload):
        actor = await get_current_professional(token="faketoken")

    assert str(actor.user_id) == user_id
    assert actor.role == UserRole.PROFESSIONAL


@pytest.mark.asyncio
async def test_get_current_manager_invalid_token():
    with patch("app.core.dependencies.decode_token", return_value=None):
        with pytest.raises(HTTPException) as exc:
            await get_current_manager(token="badtoken")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_admin_invalid_token():
    with patch("app.core.dependencies.decode_token", return_value=None):
        with pytest.raises(HTTPException) as exc:
            await get_current_admin(token="badtoken")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_professional_invalid_token():
    with patch("app.core.dependencies.decode_token", return_value=None):
        with pytest.raises(HTTPException) as exc:
            await get_current_professional(token="badtoken")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_require_any_no_matching_role():
    with patch("app.core.dependencies.decode_token", return_value=None):
        with pytest.raises(HTTPException) as exc:
            await require_any("admin", "professional")(token="badtoken")
    assert exc.value.status_code == 403
