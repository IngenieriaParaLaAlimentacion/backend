import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.user import UserRole, UserStatus
from app.exceptions.domain_exceptions import (
    BadRequestError,
    UserAlreadyExistsError,
    UserNotFoundError,
)
from app.services.admin_service import AdminService


def _make_user(email="admin@test.com"):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = email
    user.role = UserRole.ADMIN
    user.status = UserStatus.ACTIVE
    return user


def _make_pending_user(email="invitee@test.com"):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = email
    user.role = UserRole.ADMIN
    user.status = UserStatus.PENDING_VALIDATION
    return user


def _make_token(expires_at=None):
    token = MagicMock()
    token.expires_at = expires_at or datetime(2099, 1, 1, tzinfo=timezone.utc)
    return token


@pytest.fixture
def mock_auth_service():
    auth = AsyncMock()
    auth.create_recovery_token = AsyncMock(
        return_value=(_make_token(), "plain-token-abc")
    )
    return auth


@pytest.fixture
def make_uow():
    def _make(existing_user=None, created_user=None):
        uow = AsyncMock()
        uow.user_repo.get_by_email = AsyncMock(return_value=existing_user)
        uow.user_repo.create = AsyncMock(return_value=created_user or _make_user())
        uow.password_repo.create = AsyncMock()
        uow.commit = AsyncMock()
        return uow

    return _make


@pytest.fixture
def make_service(mock_auth_service):
    def _make(uow):
        return AdminService(uow, mock_auth_service)

    return _make


class TestInviteAdmin:
    @pytest.mark.asyncio
    async def test_raises_if_email_already_exists(self, make_uow, make_service):
        """Should raise UserAlreadyExistsError if email is taken."""
        existing = _make_user()
        uow = make_uow(existing_user=existing)
        service = make_service(uow)

        with pytest.raises(UserAlreadyExistsError):
            await service.invite_user(MagicMock(email=existing.email), UserRole.ADMIN)

    @pytest.mark.asyncio
    async def test_does_not_create_user_if_email_exists(self, make_uow, make_service):
        """Should not call user_repo.create if email is already registered."""
        existing = _make_user()
        uow = make_uow(existing_user=existing)
        service = make_service(uow)

        with pytest.raises(UserAlreadyExistsError):
            await service.invite_user(MagicMock(email=existing.email), UserRole.ADMIN)

        uow.user_repo.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_user_with_admin_role_and_active_status(
        self, make_uow, make_service
    ):
        """Should create user with role=ADMIN and status=ACTIVE."""
        uow = make_uow()
        service = make_service(uow)

        await service.invite_user(MagicMock(email="new@test.com"), UserRole.ADMIN)

        uow.user_repo.create.assert_called_once_with(
            email="new@test.com",
            name="",
            last_name="",
            role=UserRole.ADMIN,
            status=UserStatus.PENDING_VALIDATION,
        )

    @pytest.mark.asyncio
    async def test_creates_password_for_new_user(self, make_uow, make_service):
        """Should call password_repo.create with the new user's id."""
        created_user = _make_user()
        uow = make_uow(created_user=created_user)
        service = make_service(uow)

        await service.invite_user(MagicMock(email="new@test.com"), UserRole.ADMIN)

        uow.password_repo.create.assert_called_once()
        call_args = uow.password_repo.create.call_args
        assert call_args[0][0] == created_user.id

    @pytest.mark.asyncio
    async def test_creates_recovery_token_for_new_user(
        self, make_uow, make_service, mock_auth_service
    ):
        """Should call auth_service.create_recovery_token with the new user's id."""
        created_user = _make_user()
        uow = make_uow(created_user=created_user)
        service = make_service(uow)

        await service.invite_user(MagicMock(email="new@test.com"), UserRole.ADMIN)

        mock_auth_service.create_recovery_token.assert_called_once_with(created_user.id)

    @pytest.mark.asyncio
    async def test_sends_invite_email_with_correct_args(
        self, make_uow, make_service, mock_auth_service
    ):
        """Should call send_invite_email with user email, deeplink, and expires_at."""
        created_user = _make_user(email="invited@test.com")
        expires_at = datetime(2099, 6, 1, tzinfo=timezone.utc)
        token = _make_token(expires_at=expires_at)
        mock_auth_service.create_recovery_token = AsyncMock(
            return_value=(token, "plain-xyz")
        )

        uow = make_uow(created_user=created_user)
        service = make_service(uow)

        with (
            patch("app.services.admin_service.send_invite_email") as mock_send,
            patch(
                "app.services.admin_service.build_recovery_deeplink",
                return_value="https://deeplink/xyz",
            ),
        ):
            await service.invite_user(
                MagicMock(email="invited@test.com"), UserRole.ADMIN
            )

            mock_send.assert_called_once_with(
                "invited@test.com",
                "https://deeplink/xyz",
                expires_at,
                UserRole.ADMIN,
            )

    @pytest.mark.asyncio
    async def test_builds_deeplink_with_plain_token_and_role(
        self, make_uow, make_service, mock_auth_service
    ):
        """Should call build_recovery_deeplink with the plain token and admin role."""
        created_user = _make_user()
        mock_auth_service.create_recovery_token = AsyncMock(
            return_value=(_make_token(), "plain-xyz")
        )
        uow = make_uow(created_user=created_user)
        service = make_service(uow)

        with (
            patch(
                "app.services.admin_service.build_recovery_deeplink"
            ) as mock_deeplink,
            patch("app.services.admin_service.send_invite_email"),
        ):
            await service.invite_user(MagicMock(email="new@test.com"), UserRole.ADMIN)

            mock_deeplink.assert_called_once_with("plain-xyz", UserRole.ADMIN)

    @pytest.mark.asyncio
    async def test_does_not_commit_if_user_creation_fails(self, make_uow, make_service):
        """Should not commit if user_repo.create raises."""
        uow = make_uow()
        uow.user_repo.create = AsyncMock(side_effect=Exception("db error"))
        service = make_service(uow)

        with pytest.raises(Exception, match="db error"):
            await service.invite_user(MagicMock(email="new@test.com"), UserRole.ADMIN)

        uow.commit.assert_not_called()


class TestResendInvite:
    @pytest.mark.asyncio
    async def test_raises_if_user_not_found(self, make_uow, make_service):
        """Should raise UserNotFoundError if no user matches the id."""
        uow = make_uow()
        uow.user_repo.get_by_id = AsyncMock(return_value=None)
        service = make_service(uow)

        with pytest.raises(UserNotFoundError):
            await service.resend_invite(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_does_not_commit_if_user_not_found(self, make_uow, make_service):
        """Should not commit if the user does not exist."""
        uow = make_uow()
        uow.user_repo.get_by_id = AsyncMock(return_value=None)
        service = make_service(uow)

        with pytest.raises(UserNotFoundError):
            await service.resend_invite(uuid.uuid4())

        uow.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_if_user_already_active(self, make_uow, make_service):
        """Should raise BadRequestError if the user already completed onboarding."""
        active_user = _make_user()  # status=ACTIVE by default
        uow = make_uow()
        uow.user_repo.get_by_id = AsyncMock(return_value=active_user)
        service = make_service(uow)

        with pytest.raises(BadRequestError):
            await service.resend_invite(active_user.id)

    @pytest.mark.asyncio
    async def test_does_not_commit_if_user_already_active(self, make_uow, make_service):
        """Should not commit if the user is not pending."""
        active_user = _make_user()
        uow = make_uow()
        uow.user_repo.get_by_id = AsyncMock(return_value=active_user)
        service = make_service(uow)

        with pytest.raises(BadRequestError):
            await service.resend_invite(active_user.id)

        uow.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_create_new_user_or_password(self, make_uow, make_service):
        """Should not call user_repo.create or password_repo.create on resend."""
        pending_user = _make_pending_user()
        uow = make_uow()
        uow.user_repo.get_by_id = AsyncMock(return_value=pending_user)
        service = make_service(uow)

        with (
            patch("app.services.admin_service.send_invite_email"),
            patch(
                "app.services.admin_service.build_recovery_deeplink",
                return_value="https://deeplink/xyz",
            ),
        ):
            await service.resend_invite(pending_user.id)

        uow.user_repo.create.assert_not_called()
        uow.password_repo.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_issues_new_recovery_token_for_existing_user(
        self, make_uow, make_service, mock_auth_service
    ):
        """Should call auth_service.create_recovery_token
        with the existing user's id."""
        pending_user = _make_pending_user()
        uow = make_uow()
        uow.user_repo.get_by_id = AsyncMock(return_value=pending_user)
        service = make_service(uow)

        with (
            patch("app.services.admin_service.send_invite_email"),
            patch(
                "app.services.admin_service.build_recovery_deeplink",
                return_value="https://deeplink/xyz",
            ),
        ):
            await service.resend_invite(pending_user.id)

        mock_auth_service.create_recovery_token.assert_called_once_with(pending_user.id)

    @pytest.mark.asyncio
    async def test_commits_before_sending_email(self, make_uow, make_service):
        """Should commit the transaction before sending the resend email."""
        pending_user = _make_pending_user()
        uow = make_uow()
        uow.user_repo.get_by_id = AsyncMock(return_value=pending_user)
        service = make_service(uow)

        commit_order = []
        uow.commit = AsyncMock(side_effect=lambda: commit_order.append("commit"))

        with patch(
            "app.services.admin_service.send_invite_email",
            side_effect=lambda *a, **kw: commit_order.append("email"),
        ):
            await service.resend_invite(pending_user.id)

        assert commit_order == ["commit", "email"]

    @pytest.mark.asyncio
    async def test_sends_invite_email_with_correct_args(
        self, make_uow, make_service, mock_auth_service
    ):
        """Should call send_invite_email with the user's email,
        deeplink, and expires_at."""
        pending_user = _make_pending_user(email="pending@test.com")
        expires_at = datetime(2099, 6, 1, tzinfo=timezone.utc)
        token = _make_token(expires_at=expires_at)
        mock_auth_service.create_recovery_token = AsyncMock(
            return_value=(token, "plain-resend")
        )

        uow = make_uow()
        uow.user_repo.get_by_id = AsyncMock(return_value=pending_user)
        service = make_service(uow)

        with (
            patch("app.services.admin_service.send_invite_email") as mock_send,
            patch(
                "app.services.admin_service.build_recovery_deeplink",
                return_value="https://deeplink/resend",
            ),
        ):
            await service.resend_invite(pending_user.id)

            mock_send.assert_called_once_with(
                "pending@test.com",
                "https://deeplink/resend",
                expires_at,
                UserRole.ADMIN,
            )

    @pytest.mark.asyncio
    async def test_builds_deeplink_with_plain_token_and_user_role(
        self, make_uow, make_service, mock_auth_service
    ):
        """Should call build_recovery_deeplink with
        the new plain token and the user's role."""
        pending_user = _make_pending_user()
        mock_auth_service.create_recovery_token = AsyncMock(
            return_value=(_make_token(), "plain-resend")
        )
        uow = make_uow()
        uow.user_repo.get_by_id = AsyncMock(return_value=pending_user)
        service = make_service(uow)

        with (
            patch(
                "app.services.admin_service.build_recovery_deeplink"
            ) as mock_deeplink,
            patch("app.services.admin_service.send_invite_email"),
        ):
            await service.resend_invite(pending_user.id)

            mock_deeplink.assert_called_once_with("plain-resend", pending_user.role)
