"""Adversarial Challenge & Stress-Test Suite for backend#206.

Empirically challenges:
1. Rate limiting on POST /api/v1/auth/invite/accept (including IP isolation).
2. Decoupled password recovery: pending field worker, pending admin/analyst
   blocked, non-destructive rejection (invite token still usable after recovery
   rejection).
3. Invite acceptance: role restrictions (superadmin, field_worker, active users,
   inactive users), token re-use/replay attack, expired tokens, string boundary
   lengths (min, max, exceeded), phone regex fuzzing, and adversarial payloads
   (SQLi strings, XSS characters, Unicode).
4. Profile update null-clearing: selective clearing to SQL NULL, omitted field
   preservation, and 422 rejection of null or empty name/last_name.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import status
from sqlalchemy import select

import app.db.database as db_module
from app.config.settings import settings
from app.core.security import create_password_recovery_token, hash_password
from app.domain.user import UserRole, UserStatus
from app.models.auth.password_recovery_token import PasswordRecoveryToken
from app.models.auth.user import User
from app.models.auth.user_password import UserPassword
from tests.integration.urls import LOGIN_URL

INVITE_ACCEPT_URL = "/api/v1/auth/invite/accept"
PASSWORD_RECOVERY_CONFIRM_URL = "/api/v1/auth/password-recovery/confirm"
PASSWORD_RECOVERY_REQUEST_URL = "/api/v1/auth/password-recovery/request"
USERS_ME_URL = "/api/v1/users/me"


def _login_payload(email: str, password: str) -> dict:
    return {"email": email, "password": password, "device_id": str(uuid.uuid4())}


def _future_timestamp(hours: int = 24) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def _past_timestamp(hours: int = 1) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours)


async def _create_test_user_with_token(
    role: UserRole,
    user_status: UserStatus = UserStatus.PENDING_VALIDATION,
    is_email_verified: bool = False,
    token_used: bool = False,
    token_expired: bool = False,
) -> tuple[User, str]:
    """Helper to seed a user and a recovery/invite token in the test DB."""
    plain_token, token_hash = create_password_recovery_token()
    user_id = uuid.uuid4()
    expires_at = _past_timestamp() if token_expired else _future_timestamp()

    async with db_module.AsyncSessionLocal() as session:
        user = User(
            id=user_id,
            email=f"adv_{role.value}_{user_id.hex[:6]}@example.com",
            name="InitialName",
            last_name="InitialLastName",
            role=role,
            status=user_status,
            is_email_verified=is_email_verified,
        )
        session.add(user)
        await session.flush()
        session.add(
            UserPassword(
                user_id=user.id,
                password_hashed=hash_password("OldPassword123!"),
            )
        )
        session.add(
            PasswordRecoveryToken(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=expires_at,
                used=token_used,
            )
        )
        await session.commit()
        await session.refresh(user)

    return user, plain_token


# ==============================================================================
# 1. Adversarial Challenge: Rate Limiting on /api/v1/auth/invite/accept
# ==============================================================================


class TestAdversarialRateLimiting:
    async def test_invite_accept_rate_limit_enforced_and_isolated_by_ip(
        self, client, monkeypatch, connect_limiter_to_redis
    ):
        """Stress-test: Verify rate limiting on /api/v1/auth/invite/accept.

        When IP exceeds rate_limit_token_ip (temporarily lowered to 3/minute),
        it must return 429 Too Many Requests. A different IP must still succeed.
        """
        monkeypatch.setattr(settings, "rate_limit_token_ip", "3/minute")

        attacker_ip = "192.168.1.100"
        legitimate_ip = "192.168.1.200"

        # Make 3 calls from attacker_ip (allowed)
        for _ in range(3):
            resp = await client.post(
                INVITE_ACCEPT_URL,
                json={
                    "token": "dummy-token-rate-limit",
                    "new_password": "ValidPassword123!",
                    "name": "Rate",
                    "last_name": "Test",
                },
                headers={"X-Real-IP": attacker_ip},
            )
            # Response may be 400 (invalid token), but NOT 429
            assert resp.status_code == status.HTTP_400_BAD_REQUEST

        # 4th call from attacker_ip must be throttled with 429
        throttled_resp = await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": "dummy-token-rate-limit",
                "new_password": "ValidPassword123!",
                "name": "Rate",
                "last_name": "Test",
            },
            headers={"X-Real-IP": attacker_ip},
        )
        assert throttled_resp.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert "Retry-After" in throttled_resp.headers

        # Call from legitimate_ip must NOT be blocked (IP isolation check)
        legit_resp = await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": "dummy-token-rate-limit",
                "new_password": "ValidPassword123!",
                "name": "Rate",
                "last_name": "Test",
            },
            headers={"X-Real-IP": legitimate_ip},
        )
        assert legit_resp.status_code == status.HTTP_400_BAD_REQUEST


# ==============================================================================
# 2. Adversarial Challenge: Decoupled Password Recovery Lifecycle
# ==============================================================================


class TestAdversarialDecoupledRecovery:
    async def test_pending_field_worker_full_lifecycle(self, client):
        """Lifecycle test: Field worker pending validation resets password.

        - Status stays pending_validation.
        - Login fails with 403 /errors/account-pending-validation.
        - Token is consumed and cannot be reused.
        - Once admin activates user in DB, login with new password succeeds.
        """
        user, token = await _create_test_user_with_token(
            role=UserRole.FIELD_WORKER,
            user_status=UserStatus.PENDING_VALIDATION,
            is_email_verified=False,
        )

        # 1. Reset password
        resp = await client.post(
            PASSWORD_RECOVERY_CONFIRM_URL,
            json={"token": token, "new_password": "BrandNewPassword123!"},
        )
        assert resp.status_code == status.HTTP_204_NO_CONTENT

        # 2. Verify DB state: status still PENDING_VALIDATION, email is verified
        async with db_module.AsyncSessionLocal() as session:
            refreshed = (
                await session.execute(select(User).where(User.id == user.id))
            ).scalar_one()
            assert refreshed.status == UserStatus.PENDING_VALIDATION
            assert refreshed.is_email_verified is True

        # 3. Login attempt blocked with 403
        login_resp = await client.post(
            LOGIN_URL, json=_login_payload(user.email, "BrandNewPassword123!")
        )
        assert login_resp.status_code == status.HTTP_403_FORBIDDEN
        assert login_resp.json()["type"] == "/errors/account-pending-validation"

        # 4. Token cannot be reused
        replay_resp = await client.post(
            PASSWORD_RECOVERY_CONFIRM_URL,
            json={"token": token, "new_password": "AnotherPassword123!"},
        )
        assert replay_resp.status_code in {
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_401_UNAUTHORIZED,
        }

        # 5. Admin activates user -> login with new password now succeeds
        async with db_module.AsyncSessionLocal() as session:
            db_user = (
                await session.execute(select(User).where(User.id == user.id))
            ).scalar_one()
            db_user.status = UserStatus.ACTIVE
            await session.commit()

        active_login = await client.post(
            LOGIN_URL, json=_login_payload(user.email, "BrandNewPassword123!")
        )
        assert active_login.status_code == status.HTTP_200_OK
        assert "access_token" in active_login.json()

    async def test_pending_admin_rejection_does_not_burn_invite_token(self, client):
        """Stress-test: Pending admin attempts password recovery confirm.

        Must return 400 Bad Request (/errors/auth/invalid-recovery-token).
        Crucially, the token MUST NOT be consumed or marked used, so the admin
        can subsequently accept their invitation via /invite/accept!
        """
        user, token = await _create_test_user_with_token(
            role=UserRole.ADMIN,
            user_status=UserStatus.PENDING_VALIDATION,
        )

        # 1. Pending admin mistakenly tries /password-recovery/confirm
        bad_resp = await client.post(
            PASSWORD_RECOVERY_CONFIRM_URL,
            json={"token": token, "new_password": "NewAttemptPassword123!"},
        )
        assert bad_resp.status_code == status.HTTP_400_BAD_REQUEST
        assert bad_resp.json()["type"] == "/errors/auth/invalid-recovery-token"

        # 2. Token must NOT be marked used in DB
        async with db_module.AsyncSessionLocal() as session:
            tok_row = (
                await session.execute(
                    select(PasswordRecoveryToken).where(
                        PasswordRecoveryToken.user_id == user.id
                    )
                )
            ).scalar_one()
            assert tok_row.used is False

        # 3. User accepts invite with the same token -> SUCCESS!
        accept_resp = await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": token,
                "new_password": "ValidAcceptedPassword123!",
                "name": "AdminRescued",
                "last_name": "AdminLastName",
            },
        )
        assert accept_resp.status_code == status.HTTP_204_NO_CONTENT

        # 4. Account is now active and login works
        login_resp = await client.post(
            LOGIN_URL, json=_login_payload(user.email, "ValidAcceptedPassword123!")
        )
        assert login_resp.status_code == status.HTTP_200_OK


# ==============================================================================
# 3. Adversarial Challenge: Invite Acceptance Role & Token Restrictions
# ==============================================================================


class TestAdversarialInviteAcceptanceRestrictions:
    @pytest.mark.parametrize(
        ("role", "user_status"),
        [
            (UserRole.FIELD_WORKER, UserStatus.PENDING_VALIDATION),
            (UserRole.FIELD_WORKER, UserStatus.ACTIVE),
            (UserRole.SUPERADMIN, UserStatus.PENDING_VALIDATION),
            (UserRole.SUPERADMIN, UserStatus.ACTIVE),
            (UserRole.ADMIN, UserStatus.ACTIVE),
            (UserRole.ANALYST, UserStatus.ACTIVE),
            (UserRole.ADMIN, UserStatus.INACTIVE),
            (UserRole.ANALYST, UserStatus.INACTIVE),
        ],
    )
    async def test_invite_accept_strictly_rejects_unauthorized_roles_or_statuses(
        self, client, role, user_status
    ):
        """Stress-test: ONLY pending admin and analyst can accept invites.

        All other role/status permutations must be rejected with 400.
        """
        user, token = await _create_test_user_with_token(
            role=role,
            user_status=user_status,
        )

        resp = await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": token,
                "new_password": "ValidPassword123!",
                "name": "Restricted",
                "last_name": "User",
            },
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["type"] == "/errors/auth/invalid-recovery-token"

    async def test_invite_accept_expired_token_rejected_with_400(self, client):
        """Stress-test: Expired invite token must be rejected with 400."""
        user, token = await _create_test_user_with_token(
            role=UserRole.ANALYST,
            user_status=UserStatus.PENDING_VALIDATION,
            token_expired=True,
        )

        resp = await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": token,
                "new_password": "ValidPassword123!",
                "name": "Expired",
                "last_name": "User",
            },
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["type"] == "/errors/auth/invalid-recovery-token"

    async def test_invite_accept_replay_attack_rejected(self, client):
        """Stress-test: Consecutive submissions with same token (replay attack)."""
        user, token = await _create_test_user_with_token(
            role=UserRole.ADMIN,
            user_status=UserStatus.PENDING_VALIDATION,
        )

        payload = {
            "token": token,
            "new_password": "FirstSubmission123!",
            "name": "Accepted",
            "last_name": "Admin",
        }

        r1 = await client.post(INVITE_ACCEPT_URL, json=payload)
        assert r1.status_code == status.HTTP_204_NO_CONTENT

        r2 = await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": token,
                "new_password": "ReplayAttack123!",
                "name": "Attacker",
                "last_name": "Admin",
            },
        )
        assert r2.status_code == status.HTTP_400_BAD_REQUEST
        assert r2.json()["type"] == "/errors/auth/invalid-recovery-token"


# ==============================================================================
# 4. Adversarial Challenge: Input Boundaries, Fuzzing & Injection Payloads
# ==============================================================================


class TestAdversarialInputBoundariesAndSecurity:
    async def test_invite_accept_boundary_lengths_and_fuzzing(self, client):
        """Boundary testing:

        - name & last_name: exact min (1 char) and max (100 chars) pass; 101 fails.
        - locality: exact max (100 chars) passes; 101 fails.
        - description: exact max (500 chars) passes; 501 fails.
        - phone: exact max (20 chars) passes; 21 fails.
        """
        # 1. Min boundary (1 char)
        _, t1 = await _create_test_user_with_token(UserRole.ADMIN)
        r_min = await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": t1,
                "new_password": "ValidPassword123!",
                "name": "A",
                "last_name": "B",
                "locality": "C",
            },
        )
        assert r_min.status_code == status.HTTP_204_NO_CONTENT

        # 2. Max boundaries (100 char name/locality, 500 char desc, 20 char phone)
        _, t2 = await _create_test_user_with_token(UserRole.ANALYST)
        r_max = await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": t2,
                "new_password": "ValidPassword123!",
                "name": "N" * 100,
                "last_name": "L" * 100,
                "locality": "C" * 100,
                "description": "D" * 500,
                "contact_phone": "1" * 20,
            },
        )
        assert r_max.status_code == status.HTTP_204_NO_CONTENT

        # 3. Exceeded boundaries -> must return 422
        # Name 101 chars
        r_exceed_name = await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": "tok",
                "new_password": "ValidPassword123!",
                "name": "N" * 101,
                "last_name": "Valid",
            },
        )
        assert r_exceed_name.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

        # Locality 101 chars
        r_exceed_loc = await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": "tok",
                "new_password": "ValidPassword123!",
                "name": "Valid",
                "last_name": "Valid",
                "locality": "L" * 101,
            },
        )
        assert r_exceed_loc.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

        # Description 501 chars
        r_exceed_desc = await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": "tok",
                "new_password": "ValidPassword123!",
                "name": "Valid",
                "last_name": "Valid",
                "description": "D" * 501,
            },
        )
        assert r_exceed_desc.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

        # Phone 21 chars
        r_exceed_phone = await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": "tok",
                "new_password": "ValidPassword123!",
                "name": "Valid",
                "last_name": "Valid",
                "contact_phone": "1" * 21,
            },
        )
        assert r_exceed_phone.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.parametrize(
        "invalid_phone",
        [
            "letters-only",
            "+54 9 11 ext 432",
            "123#456",
            "phone: +5411",
            "<script>",
            "123.456.789",
        ],
    )
    async def test_invite_accept_rejects_malformed_phone_numbers(
        self, client, invalid_phone
    ):
        """Phone regex validation: only [0-9+\\-\\s()]+ allowed."""
        resp = await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": "tok",
                "new_password": "ValidPassword123!",
                "name": "Test",
                "last_name": "User",
                "contact_phone": invalid_phone,
            },
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_invite_accept_safe_with_adversarial_payloads(self, client):
        """Security stress-test: Injection strings, XSS characters, and Unicode.

        Ensures data is safely parameterized by SQLAlchemy without SQL errors,
        persisted verbatim, and returned accurately in profile.
        """
        user, token = await _create_test_user_with_token(UserRole.ANALYST)

        sqli_name = "O'Connor; DROP TABLE users;--"
        xss_last_name = "<script>alert('xss')</script>"
        unicode_locality = "São Paulo / Ñuñoa 🇦🇷"
        unicode_desc = "Bio with emojis 🥗 and quotes: \"testing\" & 'single'"

        resp = await client.post(
            INVITE_ACCEPT_URL,
            json={
                "token": token,
                "new_password": "SafePassword123!",
                "name": sqli_name,
                "last_name": xss_last_name,
                "locality": unicode_locality,
                "description": unicode_desc,
                "contact_phone": "+54 (011) 4567-8901",
            },
        )
        assert resp.status_code == status.HTTP_204_NO_CONTENT

        # Login and inspect profile to verify exact preservation
        login_resp = await client.post(
            LOGIN_URL, json=_login_payload(user.email, "SafePassword123!")
        )
        auth_header = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

        me_resp = await client.get(USERS_ME_URL, headers=auth_header)
        assert me_resp.status_code == status.HTTP_200_OK
        data = me_resp.json()
        assert data["name"] == sqli_name
        assert data["last_name"] == xss_last_name
        assert data["locality"] == unicode_locality
        assert data["description"] == unicode_desc
        assert data["contact_phone"] == "+54 (011) 4567-8901"


# ==============================================================================
# 5. Adversarial Challenge: Profile Update Null-Clearing & Non-Null Invariants
# ==============================================================================


class TestAdversarialProfileNullClearing:
    async def test_patch_me_null_clearing_and_omission_integrity(
        self, client, make_user_with_role
    ):
        """Test fine-grained null-clearing vs omitted fields behavior.

        1. Populates all profile fields.
        2. PATCHes only 'locality: null' -> locality becomes SQL NULL;
           description and contact_phone remain unchanged.
        3. PATCHes 'contact_phone: null' while updating description ->
           contact_phone becomes NULL, description is updated, locality remains NULL.
        """
        headers, user_id = await make_user_with_role(UserRole.ANALYST)

        # 1. Seed initial profile
        init_resp = await client.patch(
            USERS_ME_URL,
            json={
                "locality": "InitialLocality",
                "description": "InitialDesc",
                "contact_phone": "+541122334455",
            },
            headers=headers,
        )
        assert init_resp.status_code == status.HTTP_200_OK

        # 2. Clear only locality
        patch1 = await client.patch(
            USERS_ME_URL,
            json={"locality": None},
            headers=headers,
        )
        assert patch1.status_code == status.HTTP_200_OK
        p1_data = patch1.json()
        assert p1_data["locality"] is None
        assert p1_data["description"] == "InitialDesc"
        assert p1_data["contact_phone"] == "+541122334455"

        # Verify DB directly
        async with db_module.AsyncSessionLocal() as session:
            u1 = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one()
            assert u1.locality is None
            assert u1.description == "InitialDesc"
            assert u1.contact_phone == "+541122334455"

        # 3. Clear contact_phone while updating description
        patch2 = await client.patch(
            USERS_ME_URL,
            json={"contact_phone": None, "description": "UpdatedDescOnly"},
            headers=headers,
        )
        assert patch2.status_code == status.HTTP_200_OK
        p2_data = patch2.json()
        assert p2_data["locality"] is None
        assert p2_data["description"] == "UpdatedDescOnly"
        assert p2_data["contact_phone"] is None

        # Verify DB directly
        async with db_module.AsyncSessionLocal() as session:
            u2 = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one()
            assert u2.locality is None
            assert u2.description == "UpdatedDescOnly"
            assert u2.contact_phone is None

    @pytest.mark.parametrize(
        "invalid_patch",
        [
            {"name": None},
            {"last_name": None},
            {"name": None, "last_name": None},
            {"name": ""},
            {"name": "   "},
            {"last_name": ""},
            {"last_name": "   "},
        ],
    )
    async def test_patch_me_strictly_rejects_null_or_empty_names(
        self, client, make_user_with_role, invalid_patch
    ):
        """Non-nullable field enforcement: name and last_name non-null and non-empty."""
        headers, _ = await make_user_with_role(UserRole.ADMIN)

        resp = await client.patch(USERS_ME_URL, json=invalid_patch, headers=headers)
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_patch_me_rejects_whitespace_clearing_requiring_explicit_null(
        self, client, make_user_with_role
    ):
        """Enforces schema convention: clearing optional fields requires explicit null,

        not whitespace strings.
        """
        headers, _ = await make_user_with_role(UserRole.ADMIN)

        # Whitespace for locality -> fails min_length=1 after strip -> 422
        resp = await client.patch(
            USERS_ME_URL, json={"locality": "   "}, headers=headers
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
