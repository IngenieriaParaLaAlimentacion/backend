"""End-to-End & Cross-Feature Integration Suite for backend#206.

Derived directly from ORIGINAL_REQUEST.md (§R1.1, §R1.2, §R1.3) and PROJECT.md.
Validates:
- Password recovery decoupling (field worker pending vs active, backoffice guard)
- Invite acceptance (valid tokens, rejection for field worker / active users)
- Profile null clearing (explicit null sets DB NULL, non-null name/last_name)
- Cross-feature combinations and lifecycle state transitions
"""

import uuid
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from fastapi import status
from sqlalchemy import select

import app.db.database as db_module
from app.core.security import hash_password, hash_token
from app.domain.user import UserRole, UserStatus
from app.models.auth.password_recovery_token import PasswordRecoveryToken
from app.models.auth.user import User
from app.models.auth.user_password import UserPassword
from tests.integration.urls import INVITE_ADMIN_URL, LOGIN_URL

INVITE_ANALYST_URL = "/api/v1/admin/invite-analyst"
INVITE_ACCEPT_URL = "/api/v1/auth/invite/accept"
PASSWORD_RECOVERY_REQUEST_URL = "/api/v1/auth/password-recovery/request"
PASSWORD_RECOVERY_CONFIRM_URL = "/api/v1/auth/password-recovery/confirm"
USERS_ME_URL = "/api/v1/users/me"
ESTABLISHMENTS_REQUEST_URL = "/api/v1/users/me/establishments"
ESTABLISHMENTS_WITHDRAW_URL = "/api/v1/users/me/establishments/withdraw"
ESTABLISHMENTS_SUBSCRIPTIONS_URL = "/api/v1/users/me/establishments/subscriptions"


def _extract_token_from_deeplink(deeplink: str | None) -> str:
    if not deeplink:
        raise AssertionError("Deeplink was not captured or is None")
    parsed = urlparse(deeplink)
    tokens = parse_qs(parsed.query).get("token", [])
    if not tokens or not tokens[0]:
        raise AssertionError(f"No token found in deeplink: {deeplink}")
    return tokens[0]


def _login_payload(email: str, password: str) -> dict:
    return {"email": email, "password": password, "device_id": str(uuid.uuid4())}


def _future_timestamp():
    from datetime import datetime, timedelta, timezone

    return datetime.now(timezone.utc) + timedelta(hours=24)


# ==============================================================================
# 1. E2E Invite Acceptance Flow (Feature F3 & ORIGINAL_REQUEST §R1.2)
# ==============================================================================


class TestE2EInviteAcceptance:
    async def test_analyst_full_invite_acceptance_e2e(self, client, admin_headers):
        """Tier 1: Complete analyst invite acceptance journey.

        Superadmin invites analyst -> analyst accepts with full profile and password ->
        user transitions to active -> login succeeds -> /me profile returns all fields.
        """
        email = f"analyst_{uuid.uuid4().hex[:8]}@example.com"
        captured_deeplink = None

        async def _fake_send(to_email, deeplink, expires_at, role):
            nonlocal captured_deeplink
            captured_deeplink = deeplink

        with patch("app.services.admin_service.send_invite_email", _fake_send):
            resp = await client.post(
                INVITE_ANALYST_URL, json={"email": email}, headers=admin_headers
            )
            assert resp.status_code == status.HTTP_202_ACCEPTED
            user_id = resp.json()["user_id"]

        token = _extract_token_from_deeplink(captured_deeplink)

        # Verify user is initially pending_validation
        async with db_module.AsyncSessionLocal() as session:
            user = (
                await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
            ).scalar_one()
            assert user.status == UserStatus.PENDING_VALIDATION
            assert user.is_email_verified is False

        # Accept invite with full profile
        payload = {
            "token": token,
            "new_password": "SecurePassword123!",
            "name": "Mariana",
            "last_name": "López",
            "locality": "Rosario",
            "description": "Licenciada en Nutrición con orientación comunitaria",
            "contact_phone": "+54 9 341 555-1234",
        }
        accept_resp = await client.post(INVITE_ACCEPT_URL, json=payload)
        assert accept_resp.status_code == status.HTTP_204_NO_CONTENT

        # Verify database mutations
        async with db_module.AsyncSessionLocal() as session:
            refreshed = (
                await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
            ).scalar_one()
            assert refreshed.status == UserStatus.ACTIVE
            assert refreshed.is_email_verified is True
            assert refreshed.name == "Mariana"
            assert refreshed.last_name == "López"
            assert refreshed.locality == "Rosario"
            assert (
                refreshed.description
                == "Licenciada en Nutrición con orientación comunitaria"
            )
            assert refreshed.contact_phone == "+54 9 341 555-1234"

        # Login with new credentials
        login_resp = await client.post(
            LOGIN_URL, json=_login_payload(email, "SecurePassword123!")
        )
        assert login_resp.status_code == status.HTTP_200_OK
        access_token = login_resp.json()["access_token"]

        # Fetch profile
        me_resp = await client.get(
            USERS_ME_URL, headers={"Authorization": f"Bearer {access_token}"}
        )
        assert me_resp.status_code == status.HTTP_200_OK
        me_data = me_resp.json()
        assert me_data["name"] == "Mariana"
        assert me_data["last_name"] == "López"
        assert me_data["locality"] == "Rosario"
        assert (
            me_data["description"]
            == "Licenciada en Nutrición con orientación comunitaria"
        )
        assert me_data["contact_phone"] == "+54 9 341 555-1234"
        assert me_data["role"] == "analyst"

    async def test_admin_invite_acceptance_with_optional_fields_null(
        self, client, admin_headers
    ):
        """Tier 1: Admin accepts invite with optional fields set to null."""
        email = f"admin_{uuid.uuid4().hex[:8]}@example.com"
        captured_deeplink = None

        async def _fake_send(to_email, deeplink, expires_at, role):
            nonlocal captured_deeplink
            captured_deeplink = deeplink

        with patch("app.services.admin_service.send_invite_email", _fake_send):
            resp = await client.post(
                INVITE_ADMIN_URL, json={"email": email}, headers=admin_headers
            )
            assert resp.status_code == status.HTTP_202_ACCEPTED

        token = _extract_token_from_deeplink(captured_deeplink)

        accept_resp = await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": token,
                "new_password": "AdminPassword123!",
                "name": "Carlos",
                "last_name": "Gómez",
                "locality": None,
                "description": None,
                "contact_phone": None,
            },
        )
        assert accept_resp.status_code == status.HTTP_204_NO_CONTENT

        # Login and verify profile
        login_resp = await client.post(
            LOGIN_URL, json=_login_payload(email, "AdminPassword123!")
        )
        assert login_resp.status_code == status.HTTP_200_OK
        token_auth = login_resp.json()["access_token"]

        me_resp = await client.get(
            USERS_ME_URL, headers={"Authorization": f"Bearer {token_auth}"}
        )
        assert me_resp.status_code == status.HTTP_200_OK
        assert me_resp.json()["name"] == "Carlos"
        assert me_resp.json()["locality"] is None
        assert me_resp.json()["contact_phone"] is None

    async def test_invite_token_cannot_be_reused(self, client, admin_headers):
        """Tier 2: Consumed invite tokens must be rejected on second attempt."""
        email = f"analyst_{uuid.uuid4().hex[:8]}@example.com"
        captured_deeplink = None

        async def _fake_send(to_email, deeplink, expires_at, role):
            nonlocal captured_deeplink
            captured_deeplink = deeplink

        with patch("app.services.admin_service.send_invite_email", _fake_send):
            await client.post(
                INVITE_ANALYST_URL, json={"email": email}, headers=admin_headers
            )

        token = _extract_token_from_deeplink(captured_deeplink)

        # First use -> 204
        first_resp = await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": token,
                "new_password": "ValidPassword123!",
                "name": "First",
                "last_name": "User",
            },
        )
        assert first_resp.status_code == status.HTTP_204_NO_CONTENT

        # Second use -> 400 with invalid-recovery-token
        second_resp = await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": token,
                "new_password": "OtherPassword123!",
                "name": "Second",
                "last_name": "Attempt",
            },
        )
        assert second_resp.status_code == status.HTTP_400_BAD_REQUEST
        assert second_resp.json()["type"] == "/errors/auth/invalid-recovery-token"

    async def test_invite_accept_rejects_field_worker_token(self, client):
        """Tier 2: Tokens belonging to field_worker role must be rejected with 400."""
        user_id = uuid.uuid4()
        raw_token = uuid.uuid4().hex

        async with db_module.AsyncSessionLocal() as session:
            session.add(
                User(
                    id=user_id,
                    email=f"fw_{raw_token[:6]}@example.com",
                    name="Field",
                    last_name="Worker",
                    role=UserRole.FIELD_WORKER,
                    status=UserStatus.PENDING_VALIDATION,
                )
            )
            session.add(
                UserPassword(user_id=user_id, password_hashed=hash_password("pw"))
            )
            session.add(
                PasswordRecoveryToken(
                    user_id=user_id,
                    token_hash=hash_token(raw_token),
                    expires_at=_future_timestamp(),
                    used=False,
                )
            )
            await session.commit()

        resp = await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": raw_token,
                "new_password": "NewPassword123!",
                "name": "Hacker",
                "last_name": "Attempt",
            },
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["type"] == "/errors/auth/invalid-recovery-token"

    async def test_invite_accept_rejects_active_user_token(self, client):
        """Tier 2: Tokens belonging to active users must be rejected with 400."""
        user_id = uuid.uuid4()
        raw_token = uuid.uuid4().hex

        async with db_module.AsyncSessionLocal() as session:
            session.add(
                User(
                    id=user_id,
                    email=f"active_{raw_token[:6]}@example.com",
                    name="Active",
                    last_name="Analyst",
                    role=UserRole.ANALYST,
                    status=UserStatus.ACTIVE,
                )
            )
            session.add(
                UserPassword(user_id=user_id, password_hashed=hash_password("pw"))
            )
            session.add(
                PasswordRecoveryToken(
                    user_id=user_id,
                    token_hash=hash_token(raw_token),
                    expires_at=_future_timestamp(),
                    used=False,
                )
            )
            await session.commit()

        resp = await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": raw_token,
                "new_password": "NewPassword123!",
                "name": "Active",
                "last_name": "Analyst",
            },
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["type"] == "/errors/auth/invalid-recovery-token"

    async def test_invite_accept_validation_errors(self, client):
        """Tier 2: Validates payload schemas (name, password, phone, description)."""
        valid_token = "some-dummy-token"

        # Missing name
        r1 = await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": valid_token,
                "new_password": "ValidPassword123!",
                "last_name": "López",
            },
        )
        assert r1.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

        # Short password (<8)
        r2 = await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": valid_token,
                "new_password": "short",
                "name": "Ana",
                "last_name": "López",
            },
        )
        assert r2.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

        # Invalid phone regex
        r3 = await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": valid_token,
                "new_password": "ValidPassword123!",
                "name": "Ana",
                "last_name": "López",
                "contact_phone": "invalid-letters-phone",
            },
        )
        assert r3.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


# ==============================================================================
# 2. E2E Password Recovery Decoupling (Features F1, F2 & ORIGINAL_REQUEST §R1.1)
# ==============================================================================


class TestE2EPasswordRecoveryDecoupling:
    async def test_field_worker_pending_validation_stays_pending_after_recovery(
        self, client
    ):
        """Tier 1 & F1: Field worker resets password and stays pending_validation.

        Subsequent login must return 403 /errors/account-pending-validation.
        """
        user_id = uuid.uuid4()
        email = f"fw_{uuid.uuid4().hex[:6]}@example.com"
        raw_token = uuid.uuid4().hex

        async with db_module.AsyncSessionLocal() as session:
            session.add(
                User(
                    id=user_id,
                    email=email,
                    name="Field",
                    last_name="Worker",
                    role=UserRole.FIELD_WORKER,
                    status=UserStatus.PENDING_VALIDATION,
                    is_email_verified=False,
                )
            )
            session.add(
                UserPassword(
                    user_id=user_id, password_hashed=hash_password("initialpw")
                )
            )
            session.add(
                PasswordRecoveryToken(
                    user_id=user_id,
                    token_hash=hash_token(raw_token),
                    expires_at=_future_timestamp(),
                    used=False,
                )
            )
            await session.commit()

        # Reset password
        confirm_resp = await client.post(
            PASSWORD_RECOVERY_CONFIRM_URL,
            json={"token": raw_token, "new_password": "BrandNewPassword123!"},
        )
        assert confirm_resp.status_code == status.HTTP_204_NO_CONTENT

        # Verify DB state: status MUST still be pending_validation
        async with db_module.AsyncSessionLocal() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one()
            assert user.status == UserStatus.PENDING_VALIDATION
            assert user.is_email_verified is True

        # Attempt to login with the new password -> must receive 403 Pending Validation
        login_resp = await client.post(
            LOGIN_URL, json=_login_payload(email, "BrandNewPassword123!")
        )
        assert login_resp.status_code == status.HTTP_403_FORBIDDEN
        assert login_resp.json()["type"] == "/errors/account-pending-validation"

    async def test_pending_admin_blocked_from_password_recovery_confirm(
        self, client, admin_headers
    ):
        """Tier 1 & F2: Pending admin cannot use password-recovery/confirm."""
        email = f"pending_admin_{uuid.uuid4().hex[:6]}@example.com"
        captured_deeplink = None

        async def _fake_send(to_email, deeplink, expires_at, role):
            nonlocal captured_deeplink
            captured_deeplink = deeplink

        with patch("app.services.admin_service.send_invite_email", _fake_send):
            await client.post(
                INVITE_ADMIN_URL, json={"email": email}, headers=admin_headers
            )

        token = _extract_token_from_deeplink(captured_deeplink)

        # Attempt password recovery confirm with invite token
        resp = await client.post(
            PASSWORD_RECOVERY_CONFIRM_URL,
            json={"token": token, "new_password": "BypassAttempt123!"},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["type"] == "/errors/auth/invalid-recovery-token"

    async def test_pending_analyst_blocked_from_password_recovery_confirm(
        self, client, admin_headers
    ):
        """Tier 1 & F2: Pending analyst cannot use password-recovery/confirm."""
        email = f"pending_analyst_{uuid.uuid4().hex[:6]}@example.com"
        captured_deeplink = None

        async def _fake_send(to_email, deeplink, expires_at, role):
            nonlocal captured_deeplink
            captured_deeplink = deeplink

        with patch("app.services.admin_service.send_invite_email", _fake_send):
            await client.post(
                INVITE_ANALYST_URL, json={"email": email}, headers=admin_headers
            )

        token = _extract_token_from_deeplink(captured_deeplink)

        resp = await client.post(
            PASSWORD_RECOVERY_CONFIRM_URL,
            json={"token": token, "new_password": "BypassAttempt123!"},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["type"] == "/errors/auth/invalid-recovery-token"

    async def test_pending_backoffice_recovery_request_skips_email(
        self, client, admin_headers
    ):
        """Tier 2 & F2: Recovery request for pending backoffice skips sending email."""
        email = f"pending_admin_{uuid.uuid4().hex[:6]}@example.com"

        with patch("app.services.admin_service.send_invite_email"):
            await client.post(
                INVITE_ADMIN_URL, json={"email": email}, headers=admin_headers
            )

        with patch(
            "app.services.auth.auth_service.send_recovery_email"
        ) as mock_send_recovery:
            resp = await client.post(
                PASSWORD_RECOVERY_REQUEST_URL, json={"email": email}
            )
            assert resp.status_code == status.HTTP_202_ACCEPTED
            mock_send_recovery.assert_not_called()


# ==============================================================================
# 3. E2E Profile Null Clearing (Feature F4 & ORIGINAL_REQUEST §R1.3)
# ==============================================================================


class TestE2EProfileNullClearing:
    async def test_active_user_clear_optional_fields_to_null(
        self, client, make_user_with_role
    ):
        """Tier 1 & F4: Explicit null in PATCH /me clears optional fields to NULL."""
        headers, user_id = await make_user_with_role(UserRole.ANALYST)

        # Pre-populate optional fields in DB
        async with db_module.AsyncSessionLocal() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one()
            user.locality = "Córdoba"
            user.description = "Bio previa"
            user.contact_phone = "+54 9 351 999-8888"
            await session.commit()

        # Clear all three fields via PATCH /me
        patch_resp = await client.patch(
            USERS_ME_URL,
            json={"locality": None, "description": None, "contact_phone": None},
            headers=headers,
        )
        assert patch_resp.status_code == status.HTTP_200_OK
        data = patch_resp.json()
        assert data["locality"] is None
        assert data["description"] is None
        assert data["contact_phone"] is None

        # Confirm database columns are truly SQL NULL
        async with db_module.AsyncSessionLocal() as session:
            refreshed = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one()
            assert refreshed.locality is None
            assert refreshed.description is None
            assert refreshed.contact_phone is None

        # Subsequent GET /me verifies nulls
        get_resp = await client.get(USERS_ME_URL, headers=headers)
        assert get_resp.status_code == status.HTTP_200_OK
        assert get_resp.json()["locality"] is None
        assert get_resp.json()["description"] is None
        assert get_resp.json()["contact_phone"] is None

    async def test_active_user_cannot_set_name_or_last_name_to_null(
        self, client, make_user_with_role
    ):
        """Tier 2 & F4: name and last_name are non-nullable and return 422 if null."""
        headers, _ = await make_user_with_role(UserRole.ANALYST)

        r1 = await client.patch(USERS_ME_URL, json={"name": None}, headers=headers)
        assert r1.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

        r2 = await client.patch(USERS_ME_URL, json={"last_name": None}, headers=headers)
        assert r2.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_empty_patch_body_rejected_with_400(
        self, client, make_user_with_role
    ):
        """Tier 2 & F4: Empty JSON body {} raises EmptyUpdateRequestError (400)."""
        headers, _ = await make_user_with_role(UserRole.ANALYST)

        resp = await client.patch(USERS_ME_URL, json={}, headers=headers)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["type"] == "/errors/no-fields-to-update"


# ==============================================================================
# 4. Tier 3: Cross-Feature Combinations & Real-World Workflows
# ==============================================================================


class TestE2ECrossFeatureCombinations:
    async def test_tier3_invite_accept_then_profile_null_clearing(
        self, client, admin_headers
    ):
        """Pairwise P3: Invite accept with profile, then selectively clear fields."""
        email = f"analyst_{uuid.uuid4().hex[:8]}@example.com"
        captured_deeplink = None

        async def _fake_send(to_email, deeplink, expires_at, role):
            nonlocal captured_deeplink
            captured_deeplink = deeplink

        with patch("app.services.admin_service.send_invite_email", _fake_send):
            await client.post(
                INVITE_ANALYST_URL, json={"email": email}, headers=admin_headers
            )

        token = _extract_token_from_deeplink(captured_deeplink)

        # 1. Accept invite
        await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": token,
                "new_password": "InitialPassword123!",
                "name": "Valeria",
                "last_name": "Rios",
                "locality": "Santa Fe",
                "description": "Nutricionista clínica",
                "contact_phone": "+54 9 342 111-2222",
            },
        )

        # 2. Login
        login_resp = await client.post(
            LOGIN_URL, json=_login_payload(email, "InitialPassword123!")
        )
        auth_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

        # 3. Partially update: clear contact_phone while updating description
        patch_resp = await client.patch(
            USERS_ME_URL,
            json={
                "contact_phone": None,
                "description": "Nueva especialidad deportiva",
            },
            headers=auth_headers,
        )
        assert patch_resp.status_code == status.HTTP_200_OK
        data = patch_resp.json()
        assert data["contact_phone"] is None
        assert data["description"] == "Nueva especialidad deportiva"
        assert data["locality"] == "Santa Fe"  # preserved

    async def test_tier3_admin_invite_to_establishment_subscription(
        self, client, admin_headers, db_establishment
    ):
        """Pairwise P7: Admin accepts invite, subscribes, and unsubscribes."""
        email = f"admin_{uuid.uuid4().hex[:8]}@example.com"
        captured_deeplink = None

        async def _fake_send(to_email, deeplink, expires_at, role):
            nonlocal captured_deeplink
            captured_deeplink = deeplink

        with patch("app.services.admin_service.send_invite_email", _fake_send):
            await client.post(
                INVITE_ADMIN_URL, json={"email": email}, headers=admin_headers
            )

        token = _extract_token_from_deeplink(captured_deeplink)

        # Accept invite
        await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": token,
                "new_password": "SuperAdminPass123!",
                "name": "Admin",
                "last_name": "User",
            },
        )

        # Login
        login_resp = await client.post(
            LOGIN_URL, json=_login_payload(email, "SuperAdminPass123!")
        )
        auth_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

        # Subscribe to establishment
        sub_resp = await client.post(
            ESTABLISHMENTS_SUBSCRIPTIONS_URL,
            json={"establishment_ids": [str(db_establishment.id)]},
            headers=auth_headers,
        )
        assert sub_resp.status_code == status.HTTP_201_CREATED
        assert sub_resp.json()[0]["status"] == "approved"

        # Unsubscribe via query params
        unsub_resp = await client.delete(
            f"{ESTABLISHMENTS_SUBSCRIPTIONS_URL}?establishment_ids={db_establishment.id}",
            headers=auth_headers,
        )
        assert unsub_resp.status_code == status.HTTP_204_NO_CONTENT

    async def test_tier3_analyst_invite_to_establishment_request_and_withdraw(
        self, client, admin_headers, db_establishment
    ):
        """Pairwise P6: Analyst accepts invite, requests access, and withdraws."""
        email = f"analyst_{uuid.uuid4().hex[:8]}@example.com"
        captured_deeplink = None

        async def _fake_send(to_email, deeplink, expires_at, role):
            nonlocal captured_deeplink
            captured_deeplink = deeplink

        with patch("app.services.admin_service.send_invite_email", _fake_send):
            await client.post(
                INVITE_ANALYST_URL, json={"email": email}, headers=admin_headers
            )

        token = _extract_token_from_deeplink(captured_deeplink)

        await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": token,
                "new_password": "AnalystPass123!",
                "name": "Lucia",
                "last_name": "Analista",
            },
        )

        login_resp = await client.post(
            LOGIN_URL, json=_login_payload(email, "AnalystPass123!")
        )
        auth_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

        # Request access -> status is pending
        req_resp = await client.post(
            ESTABLISHMENTS_REQUEST_URL,
            json={"establishment_ids": [str(db_establishment.id)]},
            headers=auth_headers,
        )
        assert req_resp.status_code == status.HTTP_201_CREATED
        assert req_resp.json()[0]["status"] == "pending"

        # Withdraw access -> status becomes withdrawn
        withdraw_resp = await client.patch(
            ESTABLISHMENTS_WITHDRAW_URL,
            json={"establishment_ids": [str(db_establishment.id)]},
            headers=auth_headers,
        )
        assert withdraw_resp.status_code == status.HTTP_200_OK
        assert withdraw_resp.json()[0]["status"] == "withdrawn"
