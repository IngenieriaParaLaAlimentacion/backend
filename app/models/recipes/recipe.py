import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.models.base import Base


class RecipeRequestRecord(Base):
    """A complete recommendation request and its immutable input snapshot."""

    __tablename__ = "recipe_requests"
    __table_args__ = (
        CheckConstraint("children_count BETWEEN 1 AND 10000"),
        CheckConstraint("meal_type IN ('breakfast', 'lunch', 'snack', 'dinner')"),
        Index(
            "ix_recipe_requests_establishment_created",
            "establishment_id",
            "created_at",
            "id",
        ),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    establishment_id = Column(
        UUID(as_uuid=True), ForeignKey("establishments.id"), nullable=False
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    children_count = Column(Integer, nullable=False)
    meal_type = Column(String, nullable=False)
    input_snapshot = Column(JSONB, nullable=False)
    prompt_version = Column(String, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    proposals = relationship(
        "RecipeProposalRecord",
        cascade="all, delete-orphan",
        order_by="RecipeProposalRecord.position",
    )
    selection = relationship(
        "RecipeSelection", uselist=False, foreign_keys="RecipeSelection.request_id"
    )


class RecipeProposalRecord(Base):
    """Calculated ingredient amounts, indicators and generated preparation."""

    __tablename__ = "recipe_proposals"
    __table_args__ = (
        UniqueConstraint("request_id", "id"),
        UniqueConstraint("request_id", "position"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(
        UUID(as_uuid=True),
        ForeignKey("recipe_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    position = Column(Integer, nullable=False)
    recipe = Column(JSONB, nullable=False)


class RecipeSelection(Base):
    """The single chosen proposal and outflow for a request."""

    __tablename__ = "recipe_selections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["request_id", "proposal_id"],
            ["recipe_proposals.request_id", "recipe_proposals.id"],
        ),
    )
    request_id = Column(
        UUID(as_uuid=True),
        ForeignKey("recipe_requests.id", ondelete="CASCADE"),
        primary_key=True,
    )
    proposal_id = Column(UUID(as_uuid=True), nullable=False)
    outflow_id = Column(
        UUID(as_uuid=True), ForeignKey("food_outflows.id"), nullable=False, unique=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    chosen_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
