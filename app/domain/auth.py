from dataclasses import dataclass

from app.domain.user import UserDomain


@dataclass
class LoginDomain:
    """Result of a successful authentication."""

    user: UserDomain
    access_token: str
    refresh_token: str


@dataclass
class RefreshDomain:
    access_token: str
    refresh_token: str
