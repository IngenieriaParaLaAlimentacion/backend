import uuid

import pytest
from sqlalchemy import select

import app.db.database as db_module
from app.core.security import create_access_token
from app.domain.notifications import PushPlatform
from app.domain.user import UserRole, UserStatus
from app.models.auth.user import User
from app.models.notifications.user_push_device import UserPushDevice

pytestmark = pytest.mark.asyncio

URL = "/api/v1/users/me/devices"


async def _user() -> tuple[uuid.UUID, dict[str, str]]:
    user_id = uuid.uuid4()
    async with db_module.AsyncSessionLocal() as session:
        session.add(
            User(
                id=user_id,
                name="Push",
                last_name="User",
                email=f"{user_id}@test.com",
                role=UserRole.FIELD_WORKER,
                status=UserStatus.ACTIVE,
            )
        )
        await session.commit()
    token = create_access_token(user_id, role=UserRole.FIELD_WORKER)
    return user_id, {"Authorization": f"Bearer {token}"}


async def _devices() -> list[UserPushDevice]:
    async with db_module.AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserPushDevice).order_by(UserPushDevice.id)
        )
        return list(result.scalars().all())


def _payload(installation_id="install-1", token="token-1", name="Pixel"):
    return {
        "installation_id": installation_id,
        "fcm_token": token,
        "platform": PushPlatform.ANDROID,
        "device_name": name,
    }


async def test_register_requires_bearer_and_validates_closed_schema(client):
    assert (await client.post(URL, json=_payload())).status_code == 401
    _, headers = await _user()
    bad_platform = await client.post(
        URL, json={**_payload(), "platform": "web"}, headers=headers
    )
    extra = await client.post(
        URL, json={**_payload(), "unexpected": True}, headers=headers
    )
    assert bad_platform.status_code == 422
    assert extra.status_code == 422


async def test_register_returns_200_without_echoing_token_and_updates_metadata(client):
    user_id, headers = await _user()
    response = await client.post(URL, json=_payload(), headers=headers)
    assert response.status_code == 200
    assert response.json() == {
        "id": response.json()["id"],
        "installation_id": "install-1",
        "platform": "android",
        "device_name": "Pixel",
    }
    assert "fcm_token" not in response.json()

    updated = await client.post(
        URL,
        json=_payload(token="token-2", name="New Pixel"),
        headers=headers,
    )
    rows = await _devices()
    assert updated.status_code == 200
    assert len(rows) == 1
    assert rows[0].user_id == user_id
    assert rows[0].fcm_token == "token-2"
    assert rows[0].device_name == "New Pixel"


async def test_multiple_installations_and_global_token_reassignment(client):
    first_user_id, first_headers = await _user()
    second_user_id, second_headers = await _user()
    await client.post(URL, json=_payload(), headers=first_headers)
    await client.post(
        URL,
        json=_payload("install-2", "token-2", "Tablet"),
        headers=first_headers,
    )
    assert len(await _devices()) == 2

    response = await client.post(
        URL,
        json=_payload("install-3", "token-1", "Other"),
        headers=second_headers,
    )
    rows = await _devices()
    assert response.status_code == 200
    assert {row.installation_id for row in rows} == {"install-2", "install-3"}
    moved = next(row for row in rows if row.fcm_token == "token-1")
    assert moved.user_id == second_user_id
    retained = next(row for row in rows if row.installation_id == "install-2")
    assert retained.user_id == first_user_id


async def test_installation_reassignment_moves_owner(client):
    _, first_headers = await _user()
    second_user_id, second_headers = await _user()
    await client.post(URL, json=_payload(), headers=first_headers)
    response = await client.post(
        URL, json=_payload(token="token-new"), headers=second_headers
    )
    rows = await _devices()
    assert response.status_code == 200
    assert len(rows) == 1
    assert rows[0].user_id == second_user_id
    assert rows[0].fcm_token == "token-new"


async def test_delete_is_owner_scoped_and_idempotent(client):
    _, owner_headers = await _user()
    _, other_headers = await _user()
    await client.post(URL, json=_payload(), headers=owner_headers)

    protected = await client.delete(f"{URL}/install-1", headers=other_headers)
    assert protected.status_code == 204
    assert len(await _devices()) == 1

    deleted = await client.delete(f"{URL}/install-1", headers=owner_headers)
    repeated = await client.delete(f"{URL}/install-1", headers=owner_headers)
    assert deleted.status_code == 204
    assert repeated.status_code == 204
    assert await _devices() == []
