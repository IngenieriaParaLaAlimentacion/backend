from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from app.domain.establishment import EstablishmentDomain


class UserRole(str, Enum):
    """Roles that determine a user's permissions within the system."""

    ADMIN = "admin"
    PROFESSIONAL = "professional"
    ESTABLISHMENT_MANAGER = "establishment_manager"


class UserStatus(str, Enum):
    """Lifecycle states a user account can be in."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING_VALIDATION = "pending_validation"


@dataclass
class UserActor:
    """Identity of the authenticated user making a request."""

    user_id: UUID
    role: UserRole


@dataclass
class UserDomain:
    """Core user data as returned from persistence."""

    id: UUID
    email: str
    name: str
    last_name: str
    role: UserRole
    status: UserStatus
    establishments: list[UUID]


@dataclass
class UserWithEstablishmentsDomain:
    """User with fully hydrated establishment objects.

    Used when a response must include establishment details alongside user data.
    """

    id: UUID
    email: str
    name: str
    last_name: str
    role: UserRole
    status: UserStatus
    establishments: list[EstablishmentDomain]
