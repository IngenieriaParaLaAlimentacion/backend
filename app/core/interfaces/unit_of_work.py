from abc import ABC, abstractmethod

from app.repositories.user_password_repository import UserPasswordRepository
from app.repositories.user_repository import UserRepository
from app.repositories.user_token_repository import TokenRepository


class IUnitOfWork(ABC):
    user_repo: UserRepository
    password_repo: UserPasswordRepository
    token_repo: TokenRepository

    @abstractmethod
    def commit(self) -> None: ...

    @abstractmethod
    def rollback(self) -> None: ...

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *args):
        if exc_type:
            self.rollback()
        self.close()

    @abstractmethod
    def close(self) -> None: ...
