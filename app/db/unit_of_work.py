import app.db.database as _db
from app.core.interfaces.unit_of_work import IUnitOfWork
from app.repositories.establishment_repository import EstablishmentRepository
from app.repositories.user_establishment_repository import UserEstablishmentRepository
from app.repositories.user_password_repository import UserPasswordRepository
from app.repositories.user_repository import UserRepository
from app.repositories.user_token_repository import TokenRepository


class UnitOfWork(IUnitOfWork):
    """Concrete UnitOfWork backed by an AsyncSession.

    Usage:
        async with UnitOfWork() as uow:
            uow.user_repo.create(...)
            await uow.commit()
    """

    async def __aenter__(self):
        """Open a new async session and initialize all repositories."""
        self.session = _db.AsyncSessionLocal()
        self.user_repo = UserRepository(self.session)
        self.password_repo = UserPasswordRepository(self.session)
        self.token_repo = TokenRepository(self.session)
        self.establishment_repo = EstablishmentRepository(self.session)
        self.user_establishment_repo = UserEstablishmentRepository(self.session)
        return self

    async def commit(self) -> None:
        """Persist all pending changes to the database."""
        await self.session.commit()

    async def rollback(self) -> None:
        """Discard all pending changes since the last commit."""
        await self.session.rollback()

    async def close(self) -> None:
        """Release the session back to the connection pool."""
        await self.session.close()
