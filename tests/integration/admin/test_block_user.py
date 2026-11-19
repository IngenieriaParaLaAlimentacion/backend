import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import status
from sqlalchemy import select

import app.db.database as db_module
from app.core.security import create_access_token
from app.domain.establishment import UserEstablishmentStatus
from app.domain.user import UserRole, UserStatus
from app.domain.user_block_event import UserBlockEventType
from app.models.auth.user import User
from app.models.auth.user_block_event import UserBlockEvent
from tests.integration.admin.conftest import (
    ADMIN_USERS_URL,
    BLOCK_USER_URL,
    UNBLOCK_USER_URL,
    _insert_relation,
    _insert_user,
)
from tests.integration.admin.helpers import insert_refresh_token, is_revoked
from tests.integration.urls import LOGIN_URL, REFRESH_URL

ME_URL = "/api/v1/users/me"


async def _block(client, headers, user_id):
    return await client.patch(BLOCK_USER_URL.format(user_id=user_id), headers=headers)


async def _unblock(client, headers, user_id):
    return await client.patch(UNBLOCK_USER_URL.format(user_id=user_id), headers=headers)


both_actions = pytest.mark.parametrize(
    "action", [_block, _unblock], ids=["block", "unblock"]
)


async def _get_status(user_id: uuid.UUID) -> UserStatus:
    async with db_module.AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        return user.status


async def _get_events(user_id: uuid.UUID) -> list[UserBlockEvent]:
    async with db_module.AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserBlockEvent).where(UserBlockEvent.user_id == user_id)
        )
        return list(result.scalars().all())


@pytest_asyncio.fixture
async def admin(make_user_with_role):
    headers, _ = await make_user_with_role(UserRole.ADMIN)
    return headers


@pytest_asyncio.fixture
async def superadmin(make_user_with_role):
    headers, _ = await make_user_with_role(UserRole.SUPERADMIN)
    return headers


class TestBlockUser:
    @pytest.mark.parametrize("role", [UserRole.FIELD_WORKER, UserRole.ANALYST])
    async def test_admin_blocks_user(self, client, admin, role):
        user_id = await _insert_user(role, UserStatus.ACTIVE)

        response = await _block(client, admin, user_id)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == UserStatus.BLOCKED
        assert await _get_status(user_id) == UserStatus.BLOCKED

    async def test_superadmin_blocks_admin(self, client, superadmin):
        user_id = await _insert_user(UserRole.ADMIN, UserStatus.ACTIVE)

        response = await _block(client, superadmin, user_id)

        assert response.status_code == status.HTTP_200_OK
        assert await _get_status(user_id) == UserStatus.BLOCKED

    async def test_already_blocked_user_is_unchanged(self, client, admin):
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.BLOCKED)
        token_id = await insert_refresh_token(user_id, UserRole.FIELD_WORKER)

        response = await _block(client, admin, user_id)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == UserStatus.BLOCKED
        assert not await is_revoked(token_id)

    @pytest.mark.parametrize(
        "user_status", [UserStatus.PENDING_VALIDATION, UserStatus.INACTIVE]
    )
    async def test_user_that_is_not_active_is_rejected(
        self, client, admin, user_status
    ):
        user_id = await _insert_user(UserRole.FIELD_WORKER, user_status)

        response = await _block(client, admin, user_id)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["type"] == "/errors/user-is-not-active"
        assert await _get_status(user_id) == user_status

    async def test_status_filter_lists_only_blocked_users(self, client, admin):
        blocked_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.BLOCKED)
        await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)

        response = await client.get(
            f"{ADMIN_USERS_URL}?status={UserStatus.BLOCKED.value}", headers=admin
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert [item["id"] for item in items] == [str(blocked_id)]
        assert items[0]["status"] == UserStatus.BLOCKED


class TestUnblockUser:
    @pytest.mark.parametrize("role", [UserRole.FIELD_WORKER, UserRole.ANALYST])
    async def test_admin_unblocks_user(self, client, admin, role):
        user_id = await _insert_user(role, UserStatus.BLOCKED)

        response = await _unblock(client, admin, user_id)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == UserStatus.ACTIVE
        assert await _get_status(user_id) == UserStatus.ACTIVE

    async def test_superadmin_unblocks_admin(self, client, superadmin):
        user_id = await _insert_user(UserRole.ADMIN, UserStatus.BLOCKED)

        response = await _unblock(client, superadmin, user_id)

        assert response.status_code == status.HTTP_200_OK
        assert await _get_status(user_id) == UserStatus.ACTIVE

    async def test_keeps_approved_establishments(self, client, admin, db_establishment):
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        await _insert_relation(
            user_id, db_establishment.id, UserEstablishmentStatus.APPROVED
        )

        await _block(client, admin, user_id)
        response = await _unblock(client, admin, user_id)

        establishments = response.json()["establishments"]
        assert [e["id"] for e in establishments] == [str(db_establishment.id)]

    @pytest.mark.parametrize(
        "user_status", [UserStatus.ACTIVE, UserStatus.PENDING_VALIDATION]
    )
    async def test_user_that_is_not_blocked_is_unchanged(
        self, client, admin, user_status
    ):
        user_id = await _insert_user(UserRole.FIELD_WORKER, user_status)

        response = await _unblock(client, admin, user_id)

        assert response.status_code == status.HTTP_200_OK
        assert await _get_status(user_id) == user_status


class TestBlockAndUnblockForbidden:
    @both_actions
    async def test_admin_cannot_act_on_admin(self, client, admin, action):
        user_id = await _insert_user(UserRole.ADMIN, UserStatus.ACTIVE)

        response = await action(client, admin, user_id)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["type"] == "/errors/role-not-allowed"
        assert await _get_status(user_id) == UserStatus.ACTIVE

    @both_actions
    @pytest.mark.parametrize("actor_role", [UserRole.ADMIN, UserRole.SUPERADMIN])
    async def test_nobody_acts_on_superadmin(
        self, client, make_user_with_role, actor_role, action
    ):
        headers, _ = await make_user_with_role(actor_role)
        user_id = await _insert_user(UserRole.SUPERADMIN, UserStatus.ACTIVE)

        response = await action(client, headers, user_id)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert await _get_status(user_id) == UserStatus.ACTIVE


class TestBlockedSession:
    @pytest_asyncio.fixture
    async def blocked_session(self, client, superadmin, db_logged_in_user):
        """Log an admin in, then have a superadmin block them.

        Returns the access headers issued before the block, the refresh token, the
        device id and the user.
        """
        user, refresh_token, device_id = db_logged_in_user
        token = create_access_token(user.id, role=user.role)
        await _block(client, superadmin, user.id)
        return {"Authorization": f"Bearer {token}"}, refresh_token, device_id, user

    async def test_access_token_issued_before_the_block_is_rejected(
        self, client, blocked_session
    ):
        headers, *_ = blocked_session

        response = await client.get(ME_URL, headers=headers)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["type"] == "/errors/user-blocked"

    async def test_refresh_token_is_rejected(self, client, blocked_session):
        _, refresh_token, device_id, _ = blocked_session

        response = await client.post(
            REFRESH_URL,
            json={"refresh_token": refresh_token, "device_id": device_id},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_unblocked_user_can_log_in_again(
        self, client, superadmin, blocked_session
    ):
        *_, user = blocked_session
        await _unblock(client, superadmin, user.id)

        response = await client.post(
            LOGIN_URL,
            json={
                "email": user.email,
                "password": "correct_password",
                "device_id": str(uuid.uuid4()),
            },
        )

        assert response.status_code == status.HTTP_200_OK


class TestAuditLog:
    @pytest.mark.parametrize(
        ("action", "user_status", "event_type"),
        [
            (_block, UserStatus.ACTIVE, UserBlockEventType.BLOCKED),
            (_unblock, UserStatus.BLOCKED, UserBlockEventType.UNBLOCKED),
        ],
        ids=["block", "unblock"],
    )
    async def test_records_who_did_it_to_whom_and_when(
        self, client, make_user_with_role, action, user_status, event_type
    ):
        headers, admin_id = await make_user_with_role(UserRole.ADMIN)
        user_id = await _insert_user(UserRole.FIELD_WORKER, user_status)

        await action(client, headers, user_id)

        (event,) = await _get_events(user_id)
        assert event.actor_id == admin_id
        assert event.event_type == event_type
        assert abs(datetime.now(timezone.utc) - event.occurred_at) < timedelta(
            minutes=1
        )

    @pytest.mark.parametrize(
        ("action", "role", "user_status"),
        [
            (_block, UserRole.FIELD_WORKER, UserStatus.BLOCKED),
            (_unblock, UserRole.FIELD_WORKER, UserStatus.ACTIVE),
            (_block, UserRole.FIELD_WORKER, UserStatus.PENDING_VALIDATION),
            (_block, UserRole.ADMIN, UserStatus.ACTIVE),
        ],
        ids=[
            "already-blocked",
            "not-blocked",
            "not-active",
            "not-allowed",
        ],
    )
    async def test_requests_that_change_nothing_record_nothing(
        self, client, admin, action, role, user_status
    ):
        user_id = await _insert_user(role, user_status)

        await action(client, admin, user_id)

        assert await _get_events(user_id) == []
