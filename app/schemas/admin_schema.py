from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.domain.pagination import PaginatedResult
from app.domain.subject import SubjectDomain
from app.domain.subject_event import SubjectEventRecord
from app.schemas.establishment_schema import EstablishmentResponse
from app.schemas.pagination import PaginatedResponse
from app.schemas.subject_schema import (
    EventPayloadResponse,
    SubjectEventResponse,
    SubjectResponse,
)

# -- Request --


class EstablishmentAccessRequest(BaseModel):
    establishment_ids: Annotated[list[UUID], Field(min_length=1)]


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


class PaginatedUsersResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[UserAdminView]
    total: int
    page: int
    page_size: int
    total_pages: int


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
