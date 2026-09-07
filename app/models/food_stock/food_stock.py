import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..base import Base


class FoodStock(Base):
    """How much of a catalog food an establishment currently holds.

    A materialized balance, moved by every intake and outflow inside the same
    transaction that persists them. It answers "what is there now" — a balance
    as of a past date has to be aggregated from the movements themselves.

    A depleted food keeps its row at zero rather than being deleted: "never
    received rice" and "ran out of rice" are different answers for whoever
    plans meals from this stock.
    """

    __tablename__ = "food_stock"
    __table_args__ = (
        UniqueConstraint(
            "establishment_id", "food_id", name="uq_food_stock_establishment_id_food_id"
        ),
        CheckConstraint("quantity >= 0", name="ck_food_stock_quantity_non_negative"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    establishment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("establishments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    food_id = Column(
        UUID(as_uuid=True), ForeignKey("foods.id", ondelete="RESTRICT"), nullable=False
    )
    quantity = Column(Numeric(10, 3), nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    establishment = relationship("Establishment", back_populates="food_stock")
    food = relationship("Food")
