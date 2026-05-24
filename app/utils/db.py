from sqlalchemy.ext.asyncio import AsyncSession


def escape_like(term: str) -> str:
    """Escape special LIKE wildcard characters in a search term.

    Escapes backslash, percent, and underscore so they are treated as
    literals when passed to an ilike(..., escape="\\") call.
    """
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def execute_paginated(
    db: AsyncSession,
    base_query,
    count_query,
    order_by_col,
    limit: int,
    offset: int,
) -> tuple[list, int]:
    """Execute a paginated query and return (items, total)."""
    paginated = base_query.order_by(order_by_col).limit(limit).offset(offset)
    total = (await db.execute(count_query)).scalar_one()
    items = (await db.execute(paginated)).scalars().all()
    return items, total
