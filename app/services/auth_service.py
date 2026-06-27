from datetime import timedelta
from uuid import UUID

from app.core.config import settings
from app.core.interfaces.unit_of_work import IUnitOfWork
from app.core.password_recovery import build_recovery_deeplink, send_recovery_email
from app.core.security import (
    create_access_token,
    create_password_recovery_token,
    create_refresh_token,
    encode_refresh_token,
    hash_password,
    verify_password,
)
from app.domain.auth import LoginDomain, RefreshDomain
from app.domain.user import UserDomain, UserRole, UserStatus
from app.exceptions.domain_exceptions import (
    InvalidCredentialsError,
    InvalidTokenError,
    PendingValidationError,
    UserAlreadyExistsError,
)
from app.models import PasswordRecoveryToken
from app.schemas.auth_schema import (
    LoginRequest,
    LogoutRequest,
    PasswordRecoveryConfirmRequest,
    PasswordRecoveryRequest,
    RefreshRequest,
    RegisterFieldWorkerRequest,
)


class AuthService:
    """Service layer for authentication and token lifecycle operations."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def register_field_worker(
        self, data: RegisterFieldWorkerRequest
    ) -> UserDomain:
        """Register a new field worker. An admin has to approve
            the registration.

        Raises:
            UserAlreadyExistsError: If another user already uses the same email.
            EstablishmentNotFoundError: If any of the submitted establishment
                IDs do not exist.
        """
        if await self.uow.user_repo.get_by_email(str(data.email)):
            raise UserAlreadyExistsError(str(data.email))

        establishments = await self.uow.establishment_repo.get_all_by_ids(
            data.establishments
        )

        user = await self.uow.user_repo.create(
            email=data.email,
            name=data.name,
            last_name=data.last_name,
            role=UserRole.FIELD_WORKER,
            status=UserStatus.PENDING_VALIDATION,
        )
        await self.uow.password_repo.create(user.id, hash_password(data.password))
        for establishment in establishments:
            await self.uow.user_establishment_repo.preset_relation(
                user.id, establishment.id
            )
        await self.uow.commit()

        return UserDomain(
            id=user.id,
            email=str(user.email),
            name=user.name,
            last_name=user.last_name,
            role=user.role,
            status=user.status,
            establishments=[establishment.id for establishment in establishments],
        )

    async def login(self, data: LoginRequest) -> LoginDomain:
        """Authenticate credentials and issue access and refresh tokens.

        Returns:
            LoginDomain

        Raises:
            UserNotFoundError: If email does not belong to any user.
            PasswordNotFoundError: If stored password row is missing.
            ValueError: If password verification fails.

        Side effects:
            Persists a new refresh token hash for the given device and commits.
        """
        user = await self.uow.user_repo.get_by_email(data.email)
        if not user:
            raise InvalidCredentialsError()

        user_password = await self.uow.password_repo.get_by_user_id(user.id)
        if not user_password:
            raise InvalidCredentialsError()

        if not verify_password(data.password, user_password.password_hashed):
            raise InvalidCredentialsError()

        if user.status == UserStatus.PENDING_VALIDATION:
            raise PendingValidationError()

        access_token = create_access_token(user.id, user.role)
        refresh_token, refresh_hash = create_refresh_token()

        await self.uow.token_repo.create(
            user.id, refresh_hash, data.device_id, user.role
        )
        await self.uow.commit()

        return LoginDomain(
            user=UserDomain(
                id=user.id,
                email=str(user.email),
                name=user.name,
                last_name=user.last_name,
                role=user.role,
                status=user.status,
                establishments=[e.id for e in user.establishments],
            ),
            access_token=access_token,
            refresh_token=refresh_token,
        )

    async def logout(self, data: LogoutRequest) -> None:
        """Revoke the refresh token associated with a device.

        Raises:
            InvalidTokenError: If refresh token is invalid, expired, or revoked.

        Side effects:
            Revokes the persisted refresh token and commits the transaction.

        Note:
            Existing access tokens remain valid until they expire.
        """
        refresh_token_hash = encode_refresh_token(data.refresh_token)

        token = await self.uow.token_repo.get_active_refresh_token(
            refresh_token_hash, data.device_id
        )
        if not token:
            raise InvalidTokenError("Refresh token is invalid or expired")

        await self.uow.token_repo.revoke(token)

        await self.uow.commit()

    async def refresh(self, data: RefreshRequest) -> RefreshDomain:
        refresh_token_hash = encode_refresh_token(data.refresh_token)

        token = await self.uow.token_repo.get_active_refresh_token(
            refresh_token_hash, data.device_id
        )
        if not token:
            raise InvalidCredentialsError("Refresh token is invalid or expired.")

        await self.uow.token_repo.revoke(token)

        new_access = create_access_token(token.user_id, token.role)
        new_raw, new_hash = create_refresh_token()

        await self.uow.token_repo.create(
            user_id=token.user_id,
            token_hash=new_hash,
            device_id=data.device_id,
            role=token.role,
        )
        await self.uow.commit()

        return RefreshDomain(
            access_token=new_access,
            refresh_token=new_raw,
        )

    async def request_password_recovery(self, data: PasswordRecoveryRequest) -> None:
        """Create and email a password recovery deep link for a user.

        Notes:
            Returns without error for unknown emails to avoid user enumeration.
        """
        user = await self.uow.user_repo.get_by_email(data.email)
        if not user:
            return

        await self.uow.password_recovery_repo.revoke_active_for_user(user.id)

        recovery_token, recovery_token_hash = create_password_recovery_token()
        created_token = await self.uow.password_recovery_repo.create(
            user.id,
            recovery_token_hash,
            expires_delta=timedelta(
                minutes=settings.password_recovery_token_expire_minutes
            ),
        )

        await self.uow.commit()
        deeplink = build_recovery_deeplink(recovery_token)
        await send_recovery_email(user.email, deeplink, created_token.expires_at)

    async def confirm_password_recovery(
        self, data: PasswordRecoveryConfirmRequest
    ) -> None:
        """Validate a recovery token and update the user's password."""
        recovery_token_hash = encode_refresh_token(data.token)
        recovery_token = await self.uow.password_recovery_repo.get_active_token(
            recovery_token_hash
        )
        if not recovery_token:
            raise InvalidTokenError("Password recovery token is invalid or expired")

        user_password = await self.uow.password_repo.get_by_user_id(
            recovery_token.user_id
        )
        user_password.password_hashed = hash_password(data.new_password)
        user = await self.uow.user_repo.get_by_id(recovery_token.user_id)

        if user.status == UserStatus.PENDING_VALIDATION:
            await self.uow.user_repo.update_status(user.id, UserStatus.ACTIVE)

        await self.uow.password_recovery_repo.mark_used(recovery_token)
        await self.uow.token_repo.revoke_all_by_user_id(recovery_token.user_id)
        await self.uow.commit()

    async def create_recovery_token(
        self, user_id: UUID
    ) -> tuple[PasswordRecoveryToken, str]:
        """Revoke existing recovery tokens and create a fresh one."""
        await self.uow.password_recovery_repo.revoke_active_for_user(user_id)
        plain_token, token_hash = create_password_recovery_token()
        created = await self.uow.password_recovery_repo.create(
            user_id,
            token_hash,
            expires_delta=timedelta(
                minutes=settings.password_recovery_token_expire_minutes
            ),
        )
        return created, plain_token
