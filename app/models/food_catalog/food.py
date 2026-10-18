import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
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
    __table_args__ = (
        CheckConstraint(
            "grams_per_base_unit > 0", name="ck_foods_positive_gram_conversion"
        ),
        Index("ix_foods_category_id", "category_id"),
        Index("ix_foods_gapa_category_id", "gapa_category_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    category_id = Column(
        UUID(as_uuid=True),
        ForeignKey("food_categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # NULL means the food has no GAPA group (e.g. salt).
    gapa_category_id = Column(
        UUID(as_uuid=True),
        ForeignKey("gapa_food_categories.id", ondelete="RESTRICT"),
        nullable=True,
    )
    base_unit = Column(
        SAEnum(MeasurementUnit, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    grams_per_base_unit = Column(Numeric(12, 3), nullable=True)
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
    gapa_category = relationship("GapaFoodCategory", back_populates="foods")
    nutrient_values = relationship(
        "FoodNutrientValue", back_populates="food", cascade="all, delete-orphan"
    )
