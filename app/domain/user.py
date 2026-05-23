from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from app.domain.establishment import EstablishmentDomain, EstablishmentWithStatusDomain


class UserRole(str, Enum):
    """Roles that determine a user's permissions within the system."""
    SUPERADMIN = "superadmin"
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
class BaseUserDomain:
    """Shared fields for all user domain representations."""

    id: UUID
    email: str
    name: str
    last_name: str
    role: UserRole
    status: UserStatus


@dataclass
class UserDomain(BaseUserDomain):
    """Core user data as returned from persistence."""

    establishments: list[UUID]


@dataclass
class UserWithEstablishmentsDomain(BaseUserDomain):
    """User with fully hydrated establishment objects.

    Used when a response must include establishment details alongside user data.
    """

    establishments: list[EstablishmentDomain]


@dataclass
class ApprovedManagerDomain(BaseUserDomain):
    """User after admin approval, with each establishment annotated by
    approval status."""

    establishments: list[EstablishmentWithStatusDomain]
