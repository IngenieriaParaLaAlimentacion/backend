from dataclasses import dataclass, field, fields
from datetime import datetime
from enum import StrEnum
from typing import NamedTuple
from uuid import UUID

from app.domain.common_domains import normalize_optional_str
from app.domain.establishment_characterization import (
    CharacterizationStatus,
    characterization_status,
)


class UserEstablishmentStatus(StrEnum):
    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"
    REVOKED = "revoked"
    WITHDRAWN = "withdrawn"


# TODO:check if we can reuse user status for establishments,
# to have somthing like a StatusEnum
class EstablishmentRequestStatus(StrEnum):
    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"


class EstablishmentSortOrder(StrEnum):
    NEWEST = "newest"
    OLDEST = "oldest"
    NAME_ASC = "name_asc"
    NAME_DESC = "name_desc"
    CITY_ASC = "city_asc"
    CITY_DESC = "city_desc"
    PROVINCE_ASC = "province_asc"
    PROVINCE_DESC = "province_desc"


@dataclass
class EstablishmentListingParams:
    """Query parameters for a paginated establishment listing."""

    search: str | None = None
    city: str | None = None
    province: str | None = None
    sort_order: EstablishmentSortOrder = EstablishmentSortOrder.NEWEST

    def __post_init__(self) -> None:
        self.search = normalize_optional_str(self.search)
        self.city = normalize_optional_str(self.city)
        self.province = normalize_optional_str(self.province)


@dataclass
class EstablishmentDomain:
    """Establishment data as returned from persistence."""

    id: UUID
    name: str
    formatted_address: str
    latitude: float
    longitude: float
    place_id: str
    city: str
    province: str
    # Keyword-only so subclasses can still declare required fields after it.
    characterization: dict | None = field(default=None, kw_only=True)

    @property
    def characterization_status(self) -> CharacterizationStatus:
        """Whether the characterization profile holds any answer."""
        return characterization_status(self.characterization)

    @classmethod
    def from_db(cls, obj) -> "EstablishmentDomain":
        return cls(**{f.name: getattr(obj, f.name) for f in fields(cls)})


class EstablishmentApprovalResult(NamedTuple):
    """Outcome of approving a creation request: the resolved establishment,
    and whether it already existed rather than being newly created."""

    establishment: EstablishmentDomain
    reused: bool


@dataclass
class EstablishmentWithStatusDomain(EstablishmentDomain):
    """Establishment data with its approval status in the context of a field worker."""

    status: str


@dataclass
class EstablishmentRequestDomain:
    """Establishment creation request data as returned from persistence."""

    id: UUID
    user_id: UUID
    name: str
    formatted_address: str
    city: str | None
    province: str | None
    characterization: dict | None
    status: str
    created_at: datetime
    updated_at: datetime
    reviewed_by: UUID | None

    @classmethod
    def from_db(cls, obj) -> "EstablishmentRequestDomain":
        return cls(**{field.name: getattr(obj, field.name) for field in fields(cls)})


class EstablishmentCreationRequestSortOrder(StrEnum):
    NEWEST = "newest"
    OLDEST = "oldest"


@dataclass
class EstablishmentCreationRequestListingParams:
    """Query parameters for a paginated establishment request listing."""

    search: str | None = None
    city: str | None = None
    province: str | None = None
    status: EstablishmentRequestStatus | None = None
    sort_order: EstablishmentCreationRequestSortOrder = (
        EstablishmentCreationRequestSortOrder.OLDEST
    )

    def __post_init__(self) -> None:
        self.search = normalize_optional_str(self.search)
        self.city = normalize_optional_str(self.city)
        self.province = normalize_optional_str(self.province)


@dataclass
class EstablishmentCreationRequestWithRequesterDomain(EstablishmentRequestDomain):
    """Establishment creation request data with the requesting field
    worker's identity."""

    requester_name: str
    requester_last_name: str
    requester_email: str

    @classmethod
    def from_db(cls, obj) -> "EstablishmentCreationRequestWithRequesterDomain":
        base_fields = {
            field.name: getattr(obj, field.name)
            for field in fields(EstablishmentRequestDomain)
        }
        return cls(
            **base_fields,
            requester_name=obj.user.name,
            requester_last_name=obj.user.last_name,
            requester_email=obj.user.email,
        )
