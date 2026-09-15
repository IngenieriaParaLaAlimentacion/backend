import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.domain.food_outflow import FoodOutflowSource

from ..base import Base


class FoodOutflow(Base):
    """Food an establishment took out of its stock, grouping one or more items.

    ``occurred_at`` is when the food actually left and ``created_at`` when the
    row was written, so a retroactive load keeps both facts.
    """

    __tablename__ = "food_outflows"
    __table_args__ = (
        Index(
            "ix_food_outflows_establishment_id_occurred_at",
            "establishment_id",
            "occurred_at",
        ),
        Index(
            "ix_food_outflows_responsible_id_occurred_at",
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
        SAEnum(FoodOutflowSource, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    synced_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    establishment = relationship("Establishment", back_populates="food_outflows")
    responsible = relationship(
        "User",
        foreign_keys="[FoodOutflow.responsible_id]",
        back_populates="food_outflows",
    )
    items = relationship(
        "FoodOutflowItem",
        back_populates="outflow",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
