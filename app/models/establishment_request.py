import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.domain.establishment import EstablishmentRequestStatus

from .base import Base


class EstablishmentRequest(Base):
    """Notification requesting the creation of an establishment that does not
    exist in the catalog yet."""

    __tablename__ = "establishment_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name = Column(String, nullable=True)
    formatted_address = Column(String, nullable=True)
    city = Column(String, nullable=True)
    province = Column(String, nullable=True)
    reviewed_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    status = Column(
        SAEnum(
            EstablishmentRequestStatus,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        server_default="pending",
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user = relationship("User", foreign_keys=[user_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by])
