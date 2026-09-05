import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.domain.food_intake import FoodIntakeSource

from ..base import Base


class FoodIntake(Base):
    """A batch of food an establishment received, grouping one or more items.

    ``received_at`` is when the food actually arrived and ``created_at`` when
    the row was written, so a retroactive load keeps both facts.
    """

    __tablename__ = "food_intakes"
    __table_args__ = (
        Index(
            "ix_food_intakes_establishment_id_received_at",
            "establishment_id",
            "received_at",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    establishment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("establishments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    responsible_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    received_at = Column(DateTime(timezone=True), nullable=False)
    comments = Column(String, nullable=True)
    source = Column(
        SAEnum(FoodIntakeSource, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    synced_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    establishment = relationship("Establishment", back_populates="food_intakes")
    responsible = relationship(
        "User",
        foreign_keys="[FoodIntake.responsible_id]",
        back_populates="food_intakes",
    )
    items = relationship(
        "FoodIntakeItem",
        back_populates="intake",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
