import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..base import Base


class FoodIntakeItem(Base):
    """One food line of an intake: how much of a given catalog food arrived.

    The line carries no unit of its own — the unit is the referenced food's
    ``base_unit``, so a catalog correction never leaves the two disagreeing.
    """

    __tablename__ = "food_intake_items"
    __table_args__ = (
        Index("ix_food_intake_items_food_intake_id", "food_intake_id"),
        Index("ix_food_intake_items_food_id", "food_id"),
        CheckConstraint("quantity > 0", name="ck_food_intake_items_quantity_positive"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    food_intake_id = Column(
        UUID(as_uuid=True),
        ForeignKey("food_intakes.id", ondelete="CASCADE"),
        nullable=False,
    )
    food_id = Column(
        UUID(as_uuid=True), ForeignKey("foods.id", ondelete="RESTRICT"), nullable=False
    )
    quantity = Column(Numeric(10, 3), nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    intake = relationship("FoodIntake", back_populates="items")
    food = relationship("Food")
