from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from app.domain.establishment import EstablishmentDomain


class UserRole(str, Enum):
    ADMIN = "admin"
    PROFESSIONAL = "professional"
    ESTABLISHMENT_MANAGER = "establishment_manager"


class UserStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING_VALIDATION = "pending_validation"


@dataclass
class UserActor:
    user_id: UUID
    role: UserRole


@dataclass
class UserDomain:
    id: UUID
    email: str
    name: str
    last_name: str
    role: UserRole
    status: UserStatus
    establishments: list[UUID]


@dataclass
class UserWithEstablishmentsDomain:
    id: UUID
    email: str
    name: str
    last_name: str
    role: UserRole
    status: UserStatus
    establishments: list[EstablishmentDomain]
