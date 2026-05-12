from sqlalchemy import Column, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from .base import Base


class UserEstablishment(Base):
    """Association table linking users to the establishments they belong to."""

    __tablename__ = "user_establishments"

    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    establishment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("establishments.id", ondelete="CASCADE"),
        primary_key=True,
    )
