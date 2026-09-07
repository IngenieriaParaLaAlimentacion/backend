import uuid

from sqlalchemy import Column, DateTime, Float, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..base import Base


class Establishment(Base):
    """Physical site where anthropometric measurements are conducted."""

    __tablename__ = "establishments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    formatted_address = Column(String, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    place_id = Column(String, nullable=False)
    city = Column(String, nullable=False)
    province = Column(String, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    users = relationship(
        "User",
        secondary="user_establishments",
        back_populates="establishments",
    )
    measurements = relationship(
        "Measurement",
        back_populates="establishment",
    )
    food_intakes = relationship(
        "FoodIntake",
        back_populates="establishment",
    )
    food_outflows = relationship(
        "FoodOutflow",
        back_populates="establishment",
    )
    food_stock = relationship(
        "FoodStock",
        back_populates="establishment",
    )
