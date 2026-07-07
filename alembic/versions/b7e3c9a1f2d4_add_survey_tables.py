"""add survey tables

Revision ID: b7e3c9a1f2d4
Revises: f3a8c2e5d1b9
Create Date: 2026-07-06 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b7e3c9a1f2d4"
down_revision: Union[str, None] = "f3a8c2e5d1b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "surveys",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "scope",
            sa.Enum("generic", "targeted", name="surveyscope"),
            nullable=False,
        ),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "response_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Functional unique index enforcing case-insensitive survey names.
    op.create_index(
        "uq_surveys_lower_name",
        "surveys",
        [sa.text("lower(name)")],
        unique=True,
    )

    op.create_table(
        "survey_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("survey_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column(
            "response_type",
            sa.Enum(
                "text",
                "single_choice",
                "multiple_choice",
                "numeric",
                "date",
                name="responsetype",
            ),
            nullable=False,
        ),
        sa.Column("is_required", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["survey_id"],
            ["surveys.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_survey_questions_survey_id",
        "survey_questions",
        ["survey_id"],
    )

    op.create_table(
        "survey_question_options",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["survey_questions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_survey_question_options_question_id",
        "survey_question_options",
        ["question_id"],
    )

    op.create_table(
        "survey_establishments",
        sa.Column("survey_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("establishment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["survey_id"],
            ["surveys.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["establishment_id"],
            ["establishments.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("survey_id", "establishment_id"),
    )


def downgrade() -> None:
    op.drop_table("survey_establishments")
    op.drop_index(
        "ix_survey_question_options_question_id",
        table_name="survey_question_options",
    )
    op.drop_table("survey_question_options")
    op.drop_index(
        "ix_survey_questions_survey_id",
        table_name="survey_questions",
    )
    op.drop_table("survey_questions")
    op.drop_index("uq_surveys_lower_name", table_name="surveys")
    op.drop_table("surveys")
    sa.Enum(name="responsetype").drop(op.get_bind())
    sa.Enum(name="surveyscope").drop(op.get_bind())
