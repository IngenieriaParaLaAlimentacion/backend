from dataclasses import dataclass, fields
from enum import Enum, StrEnum
from uuid import UUID

from app.domain.establishment import EstablishmentDomain, EstablishmentWithStatusDomain


class UserRole(StrEnum):
    """Roles that determine a user's permissions within the system."""

    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    ANALYST = "analyst"
    FIELD_WORKER = "field_worker"


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


@dataclass(kw_only=True)
class BaseUserDomain:
    """Shared fields for all user domain representations."""

    id: UUID
    email: str
    name: str
    last_name: str
    role: UserRole
    status: UserStatus
    is_email_verified: bool
    locality: str | None = None
    description: str | None = None
    contact_phone: str | None = None


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

    @classmethod
    def from_db(
        cls, user, establishments: list[EstablishmentDomain]
    ) -> "UserWithEstablishmentsDomain":
        return cls(
            **{f.name: getattr(user, f.name) for f in fields(BaseUserDomain)},
            establishments=establishments,
        )


@dataclass
class ProfileDomain(BaseUserDomain):
    """Current user's profile. ``establishments`` is None for non-field-workers,
    and a (possibly empty) list for field workers."""

    establishments: list[EstablishmentWithStatusDomain] | None = None
