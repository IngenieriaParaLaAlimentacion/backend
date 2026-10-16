from sqlalchemy import Column, ForeignKey, Index, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID

from app.domain.establishment import UserEstablishmentStatus

from ..base import Base


class UserEstablishment(Base):
    """Association table linking users to the establishments they belong to."""

    __tablename__ = "user_establishments"
    __table_args__ = (
        Index(
            "ix_user_establishments_establishment_approved_user",
            "establishment_id",
            "user_id",
            postgresql_where=text("status = 'approved'"),
        ),
    )

    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    establishment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("establishments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    status = Column(
        SAEnum(UserEstablishmentStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
