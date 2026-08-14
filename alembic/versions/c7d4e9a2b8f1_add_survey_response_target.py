"""add survey response_target and subject-targeted responses

Replaces the establishment-based audience model (``surveys.scope`` plus the
``survey_establishments`` join table) with ``surveys.response_target``, which
says what entity a response is *about* rather than who may see the survey.
``survey_responses`` gains a nullable ``subject_id``, ``establishment_id``
becomes nullable, and a targeted entity may answer a given survey only once.

Revision ID: c7d4e9a2b8f1
Revises: 515e606ec021
Create Date: 2026-08-14 15:12:04.918273

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7d4e9a2b8f1"
down_revision: Union[str, Sequence[str], None] = "515e606ec021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

survey_response_target = sa.Enum(
    "subject", "establishment", "anonymous", name="surveyresponsetarget"
)
survey_scope = sa.Enum("generic", "targeted", name="surveyscope")


def upgrade() -> None:
    """Upgrade schema."""
    # Destructive by design. establishment_id changes meaning from "collected
    # at" to "answered by", so existing responses cannot be reinterpreted.
    # Cascades to survey_response_edits via its ON DELETE CASCADE FK.
    # response_count must be zeroed too, or surveys stay edit-locked despite
    # having no responses.
    op.execute("DELETE FROM survey_responses")
    op.execute("UPDATE surveys SET response_count = 0")

    survey_response_target.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "surveys",
        sa.Column(
            "response_target",
            survey_response_target,
            nullable=False,
            server_default="anonymous",
        ),
    )
    # The default exists only to backfill existing rows; new surveys must choose.
    op.alter_column("surveys", "response_target", server_default=None)

    op.drop_column("surveys", "scope")
    survey_scope.drop(op.get_bind(), checkfirst=True)

    op.drop_table("survey_establishments")

    op.add_column(
        "survey_responses",
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_survey_responses_subject_id_subjects",
        "survey_responses",
        "subjects",
        ["subject_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_survey_responses_subject_id", "survey_responses", ["subject_id"]
    )
    op.alter_column("survey_responses", "establishment_id", nullable=True)

    # A response targets at most one entity. Which one is *required* depends on
    # the survey's response_target and is enforced in the service layer.
    op.create_check_constraint(
        "ck_survey_responses_single_target",
        "survey_responses",
        "num_nonnulls(subject_id, establishment_id) <= 1",
    )
    # Partial, so anonymous responses (both columns null) stay unconstrained.
    op.create_index(
        "uq_survey_responses_survey_establishment",
        "survey_responses",
        ["survey_id", "establishment_id"],
        unique=True,
        postgresql_where=sa.text("establishment_id IS NOT NULL"),
    )
    op.create_index(
        "uq_survey_responses_survey_subject",
        "survey_responses",
        ["survey_id", "subject_id"],
        unique=True,
        postgresql_where=sa.text("subject_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade schema.

    Cannot restore the responses deleted by ``upgrade``. Responses recorded
    after the upgrade with no establishment (subject-targeted or anonymous) are
    deleted, since ``establishment_id`` becomes NOT NULL again.
    """
    op.drop_index("uq_survey_responses_survey_subject", table_name="survey_responses")
    op.drop_index(
        "uq_survey_responses_survey_establishment", table_name="survey_responses"
    )
    op.drop_constraint(
        "ck_survey_responses_single_target", "survey_responses", type_="check"
    )

    op.execute("DELETE FROM survey_responses WHERE establishment_id IS NULL")
    op.alter_column("survey_responses", "establishment_id", nullable=False)
    op.drop_index("ix_survey_responses_subject_id", table_name="survey_responses")
    op.drop_constraint(
        "fk_survey_responses_subject_id_subjects",
        "survey_responses",
        type_="foreignkey",
    )
    op.drop_column("survey_responses", "subject_id")

    op.create_table(
        "survey_establishments",
        sa.Column("survey_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("establishment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["survey_id"], ["surveys.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["establishment_id"], ["establishments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("survey_id", "establishment_id"),
    )

    survey_scope.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "surveys",
        sa.Column("scope", survey_scope, nullable=False, server_default="generic"),
    )
    op.alter_column("surveys", "scope", server_default=None)
    op.drop_column("surveys", "response_target")
    survey_response_target.drop(op.get_bind(), checkfirst=True)
