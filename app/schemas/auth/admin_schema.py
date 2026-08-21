from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.domain.pagination import PaginatedResult
from app.domain.subject import SubjectDomain
from app.domain.subject_event import SubjectEventRecord
from app.domain.user import UserWithEstablishmentsDomain
from app.schemas.common import ProfileFields
from app.schemas.establishments.establishment_schema import EstablishmentResponse
from app.schemas.pagination import PaginatedResponse
from app.schemas.subjects.subject_schema import (
    EventPayloadResponse,
    SubjectEventResponse,
    SubjectResponse,
)

# -- Request --


class UserAccessRequest(BaseModel):
    """Establishment ids an admin approves while accepting a field worker.

    May be empty: the account is accepted and every request stays pending.
    """

    establishment_ids: list[UUID]


class InviteAdminRequest(BaseModel):
    email: EmailStr


# -- Response --


class UserAdminView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    name: str
    last_name: str
    role: str
    status: str
    is_email_verified: bool
    establishments: list[EstablishmentResponse]


class FullUserAdminView(ProfileFields):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    name: str
    last_name: str
    role: str
    status: str
    establishments: list[EstablishmentResponse]


class PaginatedUsersResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[UserAdminView]
    total: int
    page: int
    page_size: int
    total_pages: int


class PendingEstablishmentsResponse(PaginatedUsersResponse):
    """Active field workers awaiting establishment access.

    Every item's ``establishments`` holds only that field worker's pending
    establishments.
    """

    total_pending_establishments: int = Field(
        description="Pending establishment relations across every field worker "
        "matching the current filters, not just the ones on this page."
    )

    @classmethod
    def from_domain(
        cls,
        result: PaginatedResult[UserWithEstablishmentsDomain],
        total_pending: int,
    ) -> "PendingEstablishmentsResponse":
        return cls.model_validate(
            {**result.__dict__, "total_pending_establishments": total_pending}
        )


class AdminSubjectDetailResponse(SubjectResponse):
    events: PaginatedResponse[SubjectEventResponse]

    @classmethod
    def from_domain(
        cls,
        subject: SubjectDomain,
        history: PaginatedResult[SubjectEventRecord],
    ) -> "AdminSubjectDetailResponse":
        return cls.model_validate(
            {
                **subject.__dict__,
                "events": PaginatedResponse[SubjectEventResponse](
                    items=[
                        SubjectEventResponse(
                            event_type=event.event_type,
                            occurred_at=event.occurred_at,
                            actor_id=event.actor_id,
                            payload=EventPayloadResponse(
                                before=event.payload.before,
                                after=event.payload.after,
                            ),
                        )
                        for event in history.items
                    ],
                    total=history.total,
                    page=history.page,
                    page_size=history.page_size,
                    total_pages=history.total_pages,
                ),
            }
        )


class InviteUserResponse(BaseModel):
    user_id: UUID = Field(
        description="ID of the newly created user. Use it to drive "
        "the resend-invitation action."
    )
