from app.core.interfaces.unit_of_work import IUnitOfWork
from app.core.security import hash_password
from app.domain.user import UserDomain, UserRole, UserStatus
from app.exceptions.domain_exceptions import UserAlreadyExistsError
from app.schemas.auth_schema import RegisterManagerRequest


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
