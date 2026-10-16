import uuid

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.domain.food_catalog import MeasurementUnit

from ..base import Base


class Food(Base):
    """A specific food an establishment can select when logging stock received."""

    __tablename__ = "foods"
    __table_args__ = (Index("ix_foods_category_id", "category_id"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    category_id = Column(
        UUID(as_uuid=True),
        ForeignKey("food_categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    base_unit = Column(
        SAEnum(MeasurementUnit, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    source_page = Column(SmallInteger, nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    category = relationship("FoodCategory", back_populates="foods")
    nutrient_values = relationship(
        "FoodNutrientValue", back_populates="food", cascade="all, delete-orphan"
    )
