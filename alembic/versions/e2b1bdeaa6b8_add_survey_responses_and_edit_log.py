"""add survey responses and edit log

Revision ID: e2b1bdeaa6b8
Revises: cf2c82cf97b4
Create Date: 2026-07-10 19:19:16.080804

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e2b1bdeaa6b8'
down_revision: Union[str, Sequence[str], None] = 'cf2c82cf97b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('survey_responses',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('survey_id', sa.UUID(), nullable=False),
    sa.Column('establishment_id', sa.UUID(), nullable=False),
    sa.Column('submitted_by_id', sa.UUID(), nullable=False),
    sa.Column('answers', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('event_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['establishment_id'], ['establishments.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['submitted_by_id'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['survey_id'], ['surveys.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_survey_responses_establishment_id'), 'survey_responses', ['establishment_id'], unique=False)
    op.create_index(op.f('ix_survey_responses_submitted_by_id'), 'survey_responses', ['submitted_by_id'], unique=False)
    op.create_index(op.f('ix_survey_responses_survey_id'), 'survey_responses', ['survey_id'], unique=False)
    op.create_table('survey_response_edits',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('response_id', sa.UUID(), nullable=False),
    sa.Column('edited_by_id', sa.UUID(), nullable=False),
    sa.Column('answers', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('event_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['edited_by_id'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['response_id'], ['survey_responses.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_survey_response_edits_response_id'), 'survey_response_edits', ['response_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_survey_response_edits_response_id'), table_name='survey_response_edits')
    op.drop_table('survey_response_edits')
    op.drop_index(op.f('ix_survey_responses_survey_id'), table_name='survey_responses')
    op.drop_index(op.f('ix_survey_responses_submitted_by_id'), table_name='survey_responses')
    op.drop_index(op.f('ix_survey_responses_establishment_id'), table_name='survey_responses')
    op.drop_table('survey_responses')
