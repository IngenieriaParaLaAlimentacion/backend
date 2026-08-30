import uuid

from sqlalchemy import (
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


class FoodNutrientValue(Base):
    """A single (food, nutrient) reading, exactly as SARA 2 states it per 100g."""

    __tablename__ = "food_nutrient_values"
    __table_args__ = (
        UniqueConstraint(
            "food_id", "nutrient_id", name="uq_food_nutrient_values_food_id_nutrient_id"
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    food_id = Column(
        UUID(as_uuid=True), ForeignKey("foods.id", ondelete="CASCADE"), nullable=False
    )
    nutrient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("nutrients.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount_per_100g = Column(Numeric(10, 4), nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    food = relationship("Food", back_populates="nutrient_values")
    nutrient = relationship("Nutrient", back_populates="food_values")
