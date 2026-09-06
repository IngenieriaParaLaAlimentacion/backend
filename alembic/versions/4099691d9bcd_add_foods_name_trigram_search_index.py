"""add foods name trigram search index

Revision ID: 4099691d9bcd
Revises: 8076ce393029
Create Date: 2026-09-06 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4099691d9bcd"
down_revision: Union[str, Sequence[str], None] = "8076ce393029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Trigram search on foods.name, accent- and case-insensitive.

    pg_trgm is already enabled (see eb850f66c679). unaccent's built-in
    function is STABLE, not IMMUTABLE, so it can't be used directly inside a
    functional index -- immutable_unaccent wraps it as IMMUTABLE so
    ix_foods_name_trgm can be built on immutable_unaccent(lower(name)).

    Both unaccent() and the "unaccent" dictionary are schema-qualified
    (public.unaccent / 'public.unaccent'::regdictionary): CREATE INDEX runs
    with search_path restricted to pg_catalog, so an unqualified reference
    can't find either one, even though they resolve fine outside of it.
    """
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION immutable_unaccent(text)
        RETURNS text AS $$
          SELECT public.unaccent('public.unaccent'::regdictionary, $1)
        $$ LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
        """
    )
    op.execute(
        """
        CREATE INDEX ix_foods_name_trgm
        ON foods
        USING GIN (immutable_unaccent(lower(name)) gin_trgm_ops)
        """
    )


def downgrade() -> None:
    """Drop the trigram search index, function and unaccent extension.

    pg_trgm itself is left alone -- eb850f66c679 enabled it for the subjects
    trigram indexes and still depends on it.
    """
    op.execute("DROP INDEX IF EXISTS ix_foods_name_trgm")
    op.execute("DROP FUNCTION IF EXISTS immutable_unaccent(text)")
    op.execute("DROP EXTENSION IF EXISTS unaccent")
