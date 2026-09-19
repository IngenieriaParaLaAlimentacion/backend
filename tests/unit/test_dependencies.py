from unittest.mock import patch
from uuid import uuid4

import pytest
from jose import JWTError

from app.core.dependencies import (
    get_stale_establishment_notification_service,
    require_admin,
    require_admin_or_analyst,
    require_any,
    require_internal_cron,
)
from app.exceptions.domain_exceptions import (
    ForbiddenError,
    InternalAuthenticationError,
    NotificationConfigurationError,
    UnauthorizedError,
)
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


@pytest.mark.asyncio
@pytest.mark.parametrize("provided", [None, "wrong"])
async def test_require_internal_cron_rejects_missing_or_wrong_secret(provided):
    with patch(
        "app.core.dependencies.settings.stale_notifications_cron_secret", "expected"
    ):
        with pytest.raises(InternalAuthenticationError):
            await require_internal_cron(provided)


@pytest.mark.asyncio
async def test_require_internal_cron_uses_constant_time_comparison():
    with (
        patch(
            "app.core.dependencies.settings.stale_notifications_cron_secret",
            "expected",
        ),
        patch(
            "app.core.dependencies.secrets.compare_digest", return_value=True
        ) as compare,
    ):
        await require_internal_cron("provided")
    compare.assert_called_once_with("provided", "expected")


def test_malformed_fcm_credentials_raise_canonical_configuration_error():
    with (
        patch("app.core.dependencies.settings.fcm_project_id", "project"),
        patch(
            "app.core.dependencies.settings.fcm_client_email",
            "sender@example.test",
        ),
        patch("app.core.dependencies.settings.fcm_private_key", "not-a-private-key"),
        patch("app.core.dependencies.FcmClient", side_effect=ValueError("malformed")),
    ):
        with pytest.raises(NotificationConfigurationError):
            get_stale_establishment_notification_service()
