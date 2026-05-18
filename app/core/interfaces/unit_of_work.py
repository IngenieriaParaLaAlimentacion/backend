from abc import ABC, abstractmethod

from app.repositories.user_password_repository import UserPasswordRepository
from app.repositories.user_repository import UserRepository
from app.repositories.user_token_repository import TokenRepository


class IUnitOfWork(ABC):
    user_repo: UserRepository
    password_repo: UserPasswordRepository
    token_repo: TokenRepository

    @abstractmethod
    async def commit(self) -> None: ...

    @abstractmethod
    async def rollback(self) -> None: ...

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, *args):
        if exc_type:
            await self.rollback()
        await self.close()

    @abstractmethod
    async def close(self) -> None: ...
