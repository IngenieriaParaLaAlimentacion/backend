"""rename food_intakes.received_at to occurred_at

The two movement tables recorded the same fact under two names:
`food_intakes.received_at` and `food_outflows.occurred_at` are both "when the
movement actually happened, as opposed to when the row was written". Every read
that merges the two -- the activity feed and the establishment movement listing
-- had to relabel one side to line the union's columns up, and every shared
domain and schema carried a comment explaining the mismatch.

`occurred_at` is the name that fits both: "received" only makes sense for an
intake. Renaming the intake column removes the relabelling and lets one
`_from_movement` serve both directions.

The two indexes leading with the column are renamed to match, so their names
keep describing what they index. A rename is metadata-only in PostgreSQL --
no table rewrite, no index rebuild -- so this is safe on a populated table.

Revision ID: f3b9e1a7c204
Revises: a1c6b8d47e02
Create Date: 2026-09-19 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3b9e1a7c204"
down_revision: Union[str, Sequence[str], None] = "a1c6b8d47e02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("food_intakes", "received_at", new_column_name="occurred_at")
    op.execute(
        "ALTER INDEX ix_food_intakes_establishment_id_received_at "
        "RENAME TO ix_food_intakes_establishment_id_occurred_at"
    )
    op.execute(
        "ALTER INDEX ix_food_intakes_responsible_id_received_at "
        "RENAME TO ix_food_intakes_responsible_id_occurred_at"
    )


def downgrade() -> None:
    op.execute(
        "ALTER INDEX ix_food_intakes_responsible_id_occurred_at "
        "RENAME TO ix_food_intakes_responsible_id_received_at"
    )
    op.execute(
        "ALTER INDEX ix_food_intakes_establishment_id_occurred_at "
        "RENAME TO ix_food_intakes_establishment_id_received_at"
    )
    op.alter_column("food_intakes", "occurred_at", new_column_name="received_at")
