from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.domain_exceptions import UniqueConstraintError


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
    order_by,
    limit: int,
    offset: int,
) -> tuple[list, int]:
    """Execute a paginated query and return (items, total).

    ``order_by`` accepts a single sort criterion or several, e.g. a main
    criterion plus a tiebreaker for values it doesn't sort uniquely.
    """
    order_by_clauses = order_by if isinstance(order_by, (list, tuple)) else (order_by,)
    paginated = base_query.order_by(*order_by_clauses).limit(limit).offset(offset)
    total = (await db.execute(count_query)).scalar_one()
    items = (await db.execute(paginated)).scalars().all()
    return items, total


async def insert_with_savepoint(db: AsyncSession, entity, field: str, value) -> object:
    """Insert ``entity`` inside a SAVEPOINT, mapping unique violations.

    The SAVEPOINT rolls back only the failed row, leaving the session usable
    for the caller to re-query.

    Raises:
        UniqueConstraintError: if ``field`` is already in use. The caller is
            responsible for re-querying to decide the outcome.
    """
    try:
        async with db.begin_nested():
            db.add(entity)
            await db.flush()
    except IntegrityError:
        raise UniqueConstraintError(field, value)
    await db.refresh(entity)
    return entity
