import uuid

from sqlalchemy import UUID, Boolean, Column, DateTime, ForeignKey, Index, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import relationship

from app.domain.food_intake import FoodIntakeOriginType, FoodIntakeSource

from ..base import Base


class FoodIntake(Base):
    """A batch of food an establishment received, grouping one or more items.

    ``occurred_at`` is when the food actually arrived and ``created_at`` when
    the row was written, so a retroactive load keeps both facts.

    A correction edits the row in place and moves ``updated_at``.
    """

    __tablename__ = "food_intakes"
    __table_args__ = (
        Index(
            "ix_food_intakes_establishment_id_occurred_at",
            "establishment_id",
            "occurred_at",
        ),
        Index(
            "ix_food_intakes_responsible_id_occurred_at",
            "responsible_id",
            "occurred_at",
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
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    comments = Column(String, nullable=True)
    source = Column(
        SAEnum(FoodIntakeSource, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    origin_type = Column(
        SAEnum(FoodIntakeOriginType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    is_recurring = Column(Boolean, nullable=False)
    photo_key = Column(String, nullable=True)
    synced_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
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
