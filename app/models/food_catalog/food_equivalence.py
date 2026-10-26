import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.domain.food_catalog import EquivalenceKind, EquivalenceMatchType

from ..base import Base


class FoodEquivalence(Base):
    """A factor that relates a catalog food to grams, and where it comes from.

    A food has at most one factor of each kind. A missing row means the food
    has no equivalence of that kind.
    """

    __tablename__ = "food_equivalences"
    __table_args__ = (
        UniqueConstraint("food_id", "kind", name="uq_food_equivalences_food_id_kind"),
        CheckConstraint("value > 0", name="ck_food_equivalences_value_positive"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    food_id = Column(
        UUID(as_uuid=True), ForeignKey("foods.id", ondelete="CASCADE"), nullable=False
    )
    kind = Column(
        SAEnum(EquivalenceKind, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    value = Column(Numeric(10, 4), nullable=False)
    source = Column(String, nullable=False)
    # The food's name in the source, which rarely matches the catalog's.
    source_ref = Column(String, nullable=False)
    match_type = Column(
        SAEnum(EquivalenceMatchType, values_callable=lambda x: [e.value for e in x]),
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

    food = relationship("Food")
