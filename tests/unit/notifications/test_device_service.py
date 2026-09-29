from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.notifications import PushPlatform
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import UserNotFoundError
from app.schemas.notifications.device_schema import DeviceRegistrationRequest
from app.services.notifications.device_service import DeviceService


def _request() -> DeviceRegistrationRequest:
    return DeviceRegistrationRequest(
        installation_id="install-1",
        fcm_token="token-1",
        platform=PushPlatform.ANDROID,
        device_name="Pixel",
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("installation_id", " "),
        ("fcm_token", ""),
        ("device_name", "x" * 256),
    ],
)
async def test_registration_schema_rejects_invalid_text(field, value):
    payload = {
        "installation_id": "install-1",
        "fcm_token": "token-1",
        "platform": "android",
        "device_name": "Pixel",
    }
    payload[field] = value
    with pytest.raises(ValidationError):
        DeviceRegistrationRequest.model_validate(payload)


async def test_register_is_scoped_to_authenticated_user():
    actor = UserActor(uuid4(), UserRole.FIELD_WORKER)
    uow = SimpleNamespace(
        user_repo=SimpleNamespace(get_by_id=AsyncMock(return_value=object())),
        push_device_repo=SimpleNamespace(
            delete_conflicting_token=AsyncMock(),
            upsert_installation=AsyncMock(return_value=object()),
        ),
        commit=AsyncMock(),
    )

    await DeviceService(uow).register(actor, _request())

    uow.push_device_repo.delete_conflicting_token.assert_awaited_once_with(
        "token-1", "install-1"
    )
    uow.push_device_repo.upsert_installation.assert_awaited_once_with(
        user_id=actor.user_id,
        installation_id="install-1",
        fcm_token="token-1",
        platform=PushPlatform.ANDROID,
        device_name="Pixel",
    )
    uow.commit.assert_awaited_once()


async def test_register_rejects_token_for_deleted_user():
    actor = UserActor(uuid4(), UserRole.FIELD_WORKER)
    upsert = AsyncMock()
    uow = SimpleNamespace(
        user_repo=SimpleNamespace(get_by_id=AsyncMock(return_value=None)),
        push_device_repo=SimpleNamespace(upsert_installation=upsert),
    )

    with pytest.raises(UserNotFoundError):
        await DeviceService(uow).register(actor, _request())

    upsert.assert_not_awaited()


async def test_unregister_is_idempotent_and_owner_scoped():
    actor = UserActor(uuid4(), UserRole.FIELD_WORKER)
    delete = AsyncMock(return_value=0)
    commit = AsyncMock()
    uow = SimpleNamespace(
        push_device_repo=SimpleNamespace(delete_for_user_installation=delete),
        commit=commit,
    )

    await DeviceService(uow).unregister(actor, "install-1")

    delete.assert_awaited_once_with(actor.user_id, "install-1")
    commit.assert_awaited_once()
