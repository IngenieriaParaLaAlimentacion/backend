"""Add push devices, current stale cycles, and ephemeral delivery jobs."""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f4b8c2d91e06"
down_revision: Union[str, Sequence[str], None] = "65b1998cb602"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the minimal durable push scheduling state."""
    pushplatform = postgresql.ENUM(
        "android", "ios", name="pushplatform", create_type=False
    )
    postgresql.ENUM("android", "ios", name="pushplatform").create(
        op.get_bind(), checkfirst=True
    )

    op.create_table(
        "user_push_devices",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("installation_id", sa.String(length=255), nullable=False),
        sa.Column("fcm_token", sa.Text(), nullable=False),
        sa.Column("platform", pushplatform, nullable=False),
        sa.Column("device_name", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "installation_id", name="uq_user_push_devices_installation_id"
        ),
        sa.UniqueConstraint("fcm_token", name="uq_user_push_devices_fcm_token"),
    )
    op.create_index(
        "ix_user_push_devices_user_id",
        "user_push_devices",
        ["user_id"],
    )

    op.create_table(
        "stale_establishment_cycles",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "establishment_id",
            sa.UUID(),
            sa.ForeignKey("establishments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("last_outflow_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_threshold_hours", sa.SmallInteger(), nullable=True),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "establishment_id",
            name="uq_stale_establishment_cycles_establishment_id",
        ),
        sa.CheckConstraint(
            "next_threshold_hours IS NULL OR next_threshold_hours IN (168, 336, 504)",
            name="ck_stale_cycles_next_threshold_hours",
        ),
        sa.CheckConstraint(
            "(next_threshold_hours IS NULL) = (next_due_at IS NULL)",
            name="ck_stale_cycles_next_threshold_due_pair",
        ),
    )
    op.create_index(
        "ix_stale_establishment_cycles_next_due_at",
        "stale_establishment_cycles",
        ["next_due_at"],
        postgresql_where=sa.text("next_due_at IS NOT NULL"),
    )

    op.create_table(
        "push_delivery_jobs",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "stale_cycle_id",
            sa.UUID(),
            sa.ForeignKey("stale_establishment_cycles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "device_id",
            sa.UUID(),
            sa.ForeignKey("user_push_devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("threshold_hours", sa.SmallInteger(), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stale_cycle_id",
            "threshold_hours",
            "device_id",
            name="uq_push_delivery_jobs_cycle_threshold_device",
        ),
        sa.CheckConstraint(
            "threshold_hours IN (168, 336, 504)",
            name="ck_push_delivery_jobs_threshold_hours",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_push_delivery_jobs_attempt_count"
        ),
    )
    op.create_index(
        "ix_push_delivery_jobs_available_claimed",
        "push_delivery_jobs",
        ["available_at", "claimed_until"],
    )

    # Recipient discovery starts with one establishment and approved relations.
    op.create_index(
        "ix_user_establishments_establishment_approved_user",
        "user_establishments",
        ["establishment_id", "user_id"],
        postgresql_where=sa.text("status = 'approved'"),
    )


def downgrade() -> None:
    """Remove all push scheduling state and its enum."""
    op.drop_index(
        "ix_user_establishments_establishment_approved_user",
        table_name="user_establishments",
    )
    op.drop_index(
        "ix_push_delivery_jobs_available_claimed",
        table_name="push_delivery_jobs",
    )
    op.drop_table("push_delivery_jobs")
    op.drop_index(
        "ix_stale_establishment_cycles_next_due_at",
        table_name="stale_establishment_cycles",
    )
    op.drop_table("stale_establishment_cycles")
    op.drop_index("ix_user_push_devices_user_id", table_name="user_push_devices")
    op.drop_table("user_push_devices")
    postgresql.ENUM(name="pushplatform").drop(op.get_bind(), checkfirst=True)
