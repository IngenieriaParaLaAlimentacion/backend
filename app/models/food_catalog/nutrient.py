import uuid

from sqlalchemy import Column, DateTime, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.domain.food_catalog import NutrientGroup

from ..base import Base


class Nutrient(Base):
    """A nutritional component SARA 2 measures for each food (e.g. protein, iron)."""

    __tablename__ = "nutrients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    unit = Column(String, nullable=False)
    group = Column(
        SAEnum(NutrientGroup, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
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

    food_values = relationship("FoodNutrientValue", back_populates="nutrient")
