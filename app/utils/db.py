from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.domain_exceptions import UniqueConstraintError


def escape_like(term: str) -> str:
    """Escape special LIKE wildcard characters in a search term.

    Escapes backslash, percent, and underscore so they are treated as
    literals when passed to an ilike(..., escape="\\") call.
    """
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def ilike_condition(column, value: str):
    """Case-insensitive partial match condition for a column."""
    return column.ilike(f"%{escape_like(value)}%", escape="\\")


async def _execute_paginated_query(
    db: AsyncSession,
    base_query,
    count_query,
    order_by,
    limit: int,
    offset: int,
    conditions: Sequence,
):
    """Apply conditions/order/limit/offset and run both queries.

    Shared by ``execute_paginated`` and ``execute_paginated_rows`` — they only
    differ in how they unwrap the paginated ``Result``.
    """
    for condition in conditions:
        base_query = base_query.where(condition)
        count_query = count_query.where(condition)
    order_by_clauses = order_by if isinstance(order_by, (list, tuple)) else (order_by,)
    paginated = base_query.order_by(*order_by_clauses).limit(limit).offset(offset)
    total = (await db.execute(count_query)).scalar_one()
    result = await db.execute(paginated)
    return result, total


async def execute_paginated(
    db: AsyncSession,
    base_query,
    count_query,
    order_by,
    limit: int,
    offset: int,
    conditions: Sequence = (),
) -> tuple[list, int]:
    """Execute a paginated single-entity query and return (items, total).

    Each condition is applied (AND-combined) to both
    ``base_query`` and ``count_query`` before executing.
    ``order_by`` accepts both a single sort criterion and several criterion.

    ``base_query`` must select a single entity/column — its rows are
    unwrapped with ``.scalars()``.
    """
    result, total = await _execute_paginated_query(
        db, base_query, count_query, order_by, limit, offset, conditions
    )
    return result.scalars().all(), total


async def execute_paginated_rows(
    db: AsyncSession,
    base_query,
    count_query,
    order_by,
    limit: int,
    offset: int,
    conditions: Sequence = (),
) -> tuple[list, int]:
    """Execute a paginated multi-column query and return (rows, total).

    Each condition is applied (AND-combined) to both
    ``base_query`` and ``count_query`` before executing.
    ``order_by`` accepts both a single sort criterion and several criterion.

    ``base_query`` must select several columns (e.g. an entity plus a
    computed value) — each row comes back as a raw ``Row`` tuple, not
    unwrapped to a scalar.
    """
    result, total = await _execute_paginated_query(
        db, base_query, count_query, order_by, limit, offset, conditions
    )
    return result.all(), total


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
