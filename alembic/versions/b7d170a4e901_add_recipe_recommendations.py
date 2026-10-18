"""Add recommendation snapshots, atomic choices and cultural identities."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "b7d170a4e901"
down_revision = "a1c5e9f27b34"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create recommendation records and optional cultural and mass metadata."""
    op.add_column(
        "establishments",
        sa.Column(
            "cultural_identities",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
    )
    op.create_check_constraint(
        "ck_establishments_cultural_identities",
        "establishments",
        "cultural_identities <@ ARRAY['paraguayan','bolivian']::varchar[]",
    )
    op.add_column(
        "foods", sa.Column("grams_per_base_unit", sa.Numeric(12, 3), nullable=True)
    )
    op.create_check_constraint(
        "ck_foods_positive_gram_conversion", "foods", "grams_per_base_unit > 0"
    )
    op.create_table(
        "recipe_requests",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "establishment_id",
            sa.UUID(),
            sa.ForeignKey("establishments.id"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("children_count", sa.Integer(), nullable=False),
        sa.Column("meal_type", sa.String(), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("children_count BETWEEN 1 AND 10000"),
        sa.CheckConstraint("meal_type IN ('breakfast', 'lunch', 'snack', 'dinner')"),
    )
    op.create_index(
        "ix_recipe_requests_establishment_created",
        "recipe_requests",
        ["establishment_id", "created_at", "id"],
    )
    op.create_table(
        "recipe_proposals",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "request_id",
            sa.UUID(),
            sa.ForeignKey("recipe_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("recipe", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("request_id", "id"),
        sa.UniqueConstraint("request_id", "position"),
    )
    op.create_table(
        "recipe_selections",
        sa.Column(
            "request_id",
            sa.UUID(),
            sa.ForeignKey("recipe_requests.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("proposal_id", sa.UUID(), nullable=False),
        sa.Column(
            "outflow_id",
            sa.UUID(),
            sa.ForeignKey("food_outflows.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "chosen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["request_id", "proposal_id"],
            ["recipe_proposals.request_id", "recipe_proposals.id"],
        ),
    )


def downgrade() -> None:
    """Remove recommendation records and their optional metadata."""
    op.drop_table("recipe_selections")
    op.drop_table("recipe_proposals")
    op.drop_table("recipe_requests")
    op.drop_constraint("ck_foods_positive_gram_conversion", "foods")
    op.drop_column("foods", "grams_per_base_unit")
    op.drop_constraint("ck_establishments_cultural_identities", "establishments")
    op.drop_column("establishments", "cultural_identities")
