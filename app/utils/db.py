from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession


def escape_like(term: str) -> str:
    """Escape special LIKE wildcard characters in a search term.

    Escapes backslash, percent, and underscore so they are treated as
    literals when passed to an ilike(..., escape="\\") call.
    """
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def ilike_condition(column, value: str):
    """Case-insensitive partial match condition for a column."""
    return column.ilike(f"%{escape_like(value)}%", escape="\\")


async def execute_paginated(
    db: AsyncSession,
    base_query,
    count_query,
    order_by,
    limit: int,
    offset: int,
    conditions: Sequence = (),
) -> tuple[list, int]:
    """Execute a paginated query and return (items, total).

    Each condition in ``conditions`` is applied (AND-combined) to both
    ``base_query`` and ``count_query`` before executing.
    ``order_by`` accepts a single sort criterion or several, e.g. a main
    criterion plus a tiebreaker for values it doesn't sort uniquely.
    """
    for condition in conditions:
        base_query = base_query.where(condition)
        count_query = count_query.where(condition)
    order_by_clauses = order_by if isinstance(order_by, (list, tuple)) else (order_by,)
    paginated = base_query.order_by(*order_by_clauses).limit(limit).offset(offset)
    total = (await db.execute(count_query)).scalar_one()
    items = (await db.execute(paginated)).scalars().all()
    return items, total
