from app.core.interfaces.unit_of_work import IUnitOfWork
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.domain.auth import LoginDomain
from app.domain.user import UserDomain, UserRole, UserStatus
from app.exceptions.domain_exceptions import (
    InvalidCredentialsError,
    PendingValidationError,
    UserAlreadyExistsError,
)
from app.schemas.auth_schema import LoginRequest, RegisterManagerRequest


class AuthService:
    """Service layer for authentication and token lifecycle operations."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def register_manager(self, data: RegisterManagerRequest) -> UserDomain:
        """Register a new establishment manager. An admin has to approve
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
            role=UserRole.ESTABLISHMENT_MANAGER,
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
