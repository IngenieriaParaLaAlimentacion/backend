"""add private_donation and collection_event, merge social_organization

Revision ID: b7d2e5f1a3c8
Revises: a8c4f6d2e901
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d2e5f1a3c8"
down_revision: Union[str, Sequence[str], None] = "a8c4f6d2e901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_VALUES = (
    "national_government",
    "provincial_government",
    "municipal_government",
    "private_company",
    "foundation",
    "social_organization",
    "church",
    "other",
)
NEW_VALUES = (
    "national_government",
    "provincial_government",
    "municipal_government",
    "private_company",
    "foundation",
    "church",
    "private_donation",
    "collection_event",
    "other",
)


def _swap_origin_type(values: tuple[str, ...]) -> None:
    """Recreate foodintakeorigintype with ``values`` and re-type the column."""
    labels = ", ".join(f"'{value}'" for value in values)
    op.execute(f"CREATE TYPE foodintakeorigintype_new AS ENUM ({labels})")
    op.execute(
        "ALTER TABLE food_intakes ALTER COLUMN origin_type "
        "TYPE foodintakeorigintype_new "
        "USING origin_type::text::foodintakeorigintype_new"
    )
    op.execute("DROP TYPE foodintakeorigintype")
    op.execute("ALTER TYPE foodintakeorigintype_new RENAME TO foodintakeorigintype")


def upgrade() -> None:
    """Merge social_organization into foundation and add the two new origins."""
    op.execute(
        "UPDATE food_intakes SET origin_type = 'foundation' "
        "WHERE origin_type = 'social_organization'"
    )
    _swap_origin_type(NEW_VALUES)


def downgrade() -> None:
    """Restore the previous enum, mapping the two new origins to other."""
    # Rows merged into foundation cannot be told apart from the original ones,
    # so they stay as foundation.
    op.execute(
        "UPDATE food_intakes SET origin_type = 'other' "
        "WHERE origin_type IN ('private_donation', 'collection_event')"
    )
    _swap_origin_type(OLD_VALUES)
