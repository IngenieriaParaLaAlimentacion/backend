import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import status
from sqlalchemy import select

import app.db.database as db_module
from app.config.settings import settings
from app.core.security import create_access_token, hash_token
from app.domain.establishment import UserEstablishmentStatus
from app.domain.user import UserRole, UserStatus
from app.models.auth.user import User
from app.models.auth.user_token import UserToken
from app.repositories.auth.user_repository import UserRepository
from app.repositories.auth.user_token_repository import TokenRepository
from tests.integration.admin.conftest import (
    ADMIN_USERS_URL,
    BLOCK_USER_URL,
    UNBLOCK_USER_URL,
    _insert_relation,
    _insert_user,
)
from tests.integration.admin.helpers import insert_refresh_token, is_revoked
from tests.integration.urls import LOGIN_URL, LOGOUT_URL, REFRESH_URL

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

    @pytest.mark.parametrize("options", [{}, {"report_user_blocked": False}])
    async def test_legacy_refresh_keeps_generic_error(
        self, client, blocked_session, options
    ):
        _, token, device, _ = blocked_session

        response = await client.post(
            REFRESH_URL, json={"refresh_token": token, "device_id": device, **options}
        )

        _assert_invalid_refresh(response)

    async def test_expired_access_can_detect_block_during_refresh(
        self, client, blocked_session, monkeypatch
    ):
        _, token, device, user = blocked_session
        monkeypatch.setattr(settings, "access_token_expire_minutes", -1)
        expired = create_access_token(user.id, role=user.role)
        response = await client.get(
            ME_URL, headers={"Authorization": f"Bearer {expired}"}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

        _assert_blocked_refresh(await _refresh(client, token, device))

    async def test_wrong_device_and_unknown_token_keep_generic_error(
        self, client, blocked_session
    ):
        _, token, device, _ = blocked_session

        _assert_invalid_refresh(await _refresh(client, token, str(uuid.uuid4())))
        _assert_invalid_refresh(await _refresh(client, uuid.uuid4().hex, device))

    @pytest.mark.parametrize(
        "provenance", ["rotated", "logged_out", "legacy", "expired"]
    )
    async def test_ineligible_credentials_keep_generic_error(
        self, client, superadmin, db_logged_in_user, provenance
    ):
        user, token, device = db_logged_in_user
        if provenance == "rotated":
            assert (await _refresh(client, token, device)).status_code == 200
        elif provenance == "logged_out":
            response = await client.post(
                LOGOUT_URL, json={"refresh_token": token, "device_id": device}
            )
            assert response.status_code == 204
        else:
            async with db_module.AsyncSessionLocal() as session:
                row = await session.scalar(
                    select(UserToken).where(UserToken.token_hash == hash_token(token))
                )
                if provenance == "legacy":
                    row.revoked = True
                else:
                    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
                await session.commit()

        assert (await _block(client, superadmin, user.id)).status_code == 200
        _assert_invalid_refresh(await _refresh(client, token, device))
        assert await _revocation(token) == (True, False)

    async def test_unblock_clears_markers_and_fresh_login_restores_access(
        self, client, superadmin, blocked_session, db_establishment
    ):
        _, token, device, user = blocked_session
        await _insert_relation(
            user.id, db_establishment.id, UserEstablishmentStatus.APPROVED
        )
        _assert_blocked_refresh(await _refresh(client, token, device))
        assert await _revocation(token) == (True, True)

        await _unblock(client, superadmin, user.id)
        _assert_invalid_refresh(await _refresh(client, token, device))
        assert await _revocation(token) == (True, False)

        fresh = await _login(client, user, device)
        assert fresh.status_code == 200
        response = await client.get(
            "/api/v1/users/me/establishments",
            headers={"Authorization": f"Bearer {fresh.json()['access_token']}"},
        )
        assert response.status_code == 200
        assert str(db_establishment.id) in response.text

        await _block(client, superadmin, user.id)
        _assert_invalid_refresh(await _refresh(client, token, device))
        _assert_blocked_refresh(
            await _refresh(client, fresh.json()["refresh_token"], device)
        )

    async def test_cutoff_applies_to_multiple_devices(
        self, client, superadmin, db_logged_in_user
    ):
        user, first_token, first_device = db_logged_in_user
        second_device = str(uuid.uuid4())
        second = await _login(client, user, second_device)
        assert second.status_code == 200

        await _block(client, superadmin, user.id)

        _assert_blocked_refresh(await _refresh(client, first_token, first_device))
        _assert_blocked_refresh(
            await _refresh(client, second.json()["refresh_token"], second_device)
        )


async def _login(client, user, device):
    return await client.post(
        LOGIN_URL,
        json={"email": user.email, "password": "correct_password", "device_id": device},
    )


async def _refresh(client, token, device):
    return await client.post(
        REFRESH_URL,
        json={"refresh_token": token, "device_id": device, "report_user_blocked": True},
    )


def _assert_invalid_refresh(response):
    assert response.status_code == 401
    assert response.json()["type"] == "/errors/auth/invalid-refresh-token"


def _assert_blocked_refresh(response):
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = response.json()
    assert problem["type"] == "/errors/user-blocked"
    assert problem["instance"] == REFRESH_URL
    assert "access_token" not in problem
    assert "refresh_token" not in problem


async def _revocation(token):
    async with db_module.AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserToken.revoked, UserToken.revoked_for_block).where(
                UserToken.token_hash == hash_token(token)
            )
        )
        return result.one()


class TestConcurrentBlock:
    async def test_refresh_rechecks_credential_after_block(
        self, client, superadmin, db_logged_in_user, monkeypatch
    ):
        user, token, device = db_logged_in_user
        discovered = asyncio.Event()
        resume = asyncio.Event()
        original = TokenRepository.get_refresh_candidate_user_id

        async def pause_after_lookup(repo, *args, **kwargs):
            owner = await original(repo, *args, **kwargs)
            discovered.set()
            await asyncio.wait_for(resume.wait(), timeout=10)
            return owner

        monkeypatch.setattr(
            TokenRepository, "get_refresh_candidate_user_id", pause_after_lookup
        )
        refresh = asyncio.create_task(_refresh(client, token, device))
        try:
            await asyncio.wait_for(discovered.wait(), timeout=10)
            assert (await _block(client, superadmin, user.id)).status_code == 200
        finally:
            resume.set()
            result = await asyncio.wait_for(refresh, timeout=10)

        _assert_blocked_refresh(result)

    async def test_login_reloads_status_after_block(
        self, client, superadmin, db_logged_in_user, monkeypatch
    ):
        user, _, _ = db_logged_in_user
        discovered = asyncio.Event()
        resume = asyncio.Event()
        original = UserRepository.get_by_email

        async def pause_after_lookup(repo, *args, **kwargs):
            candidate = await original(repo, *args, **kwargs)
            discovered.set()
            await asyncio.wait_for(resume.wait(), timeout=10)
            return candidate

        monkeypatch.setattr(UserRepository, "get_by_email", pause_after_lookup)
        login = asyncio.create_task(_login(client, user, str(uuid.uuid4())))
        try:
            await asyncio.wait_for(discovered.wait(), timeout=10)
            assert (await _block(client, superadmin, user.id)).status_code == 200
        finally:
            resume.set()
            result = await asyncio.wait_for(login, timeout=10)

        assert result.status_code == 403
        assert result.json()["type"] == "/errors/user-blocked"

    async def test_block_revokes_replacement_staged_by_concurrent_refresh(
        self, client, superadmin, db_logged_in_user, monkeypatch
    ):
        user, token, device = db_logged_in_user
        staged = asyncio.Event()
        block_started = asyncio.Event()
        resume = asyncio.Event()
        create = TokenRepository.create
        lock = UserRepository.get_for_update

        async def pause_after_create(repo, *args, **kwargs):
            result = await create(repo, *args, **kwargs)
            staged.set()
            await asyncio.wait_for(resume.wait(), timeout=10)
            return result

        async def observe_lock(repo, *args, **kwargs):
            if staged.is_set():
                block_started.set()
            return await lock(repo, *args, **kwargs)

        monkeypatch.setattr(TokenRepository, "create", pause_after_create)
        monkeypatch.setattr(UserRepository, "get_for_update", observe_lock)
        refresh = asyncio.create_task(_refresh(client, token, device))
        block = None
        try:
            await asyncio.wait_for(staged.wait(), timeout=10)
            block = asyncio.create_task(_block(client, superadmin, user.id))
            await asyncio.wait_for(block_started.wait(), timeout=10)
        finally:
            resume.set()
            rotated = await asyncio.wait_for(refresh, timeout=10)
            if block is not None:
                blocked = await asyncio.wait_for(block, timeout=10)

        assert rotated.status_code == 200
        assert blocked.status_code == 200
        replacement = rotated.json()
        assert await _revocation(replacement["refresh_token"]) == (True, True)
        assert await _revocation(token) == (True, False)
        response = await client.get(
            ME_URL, headers={"Authorization": f"Bearer {replacement['access_token']}"}
        )
        assert response.status_code == 403
        assert response.json()["type"] == "/errors/user-blocked"

    async def test_simultaneous_refresh_rotates_once(self, client, db_logged_in_user):
        _, token, device = db_logged_in_user
        responses = await asyncio.wait_for(
            asyncio.gather(
                _refresh(client, token, device), _refresh(client, token, device)
            ),
            timeout=10,
        )
        assert sorted(response.status_code for response in responses) == [200, 401]
        _assert_invalid_refresh(
            next(response for response in responses if response.status_code == 401)
        )
