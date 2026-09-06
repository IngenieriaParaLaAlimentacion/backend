from collections.abc import AsyncIterator, Sequence

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.domain_exceptions import UniqueConstraintError

# Rows pulled per round trip when streaming an export. Large enough that the
# per-chunk selectin loads stay cheap, small enough that memory stays flat.
_STREAM_CHUNK = 1000


def escape_like(term: str) -> str:
    """Escape special LIKE wildcard characters in a search term.

    Escapes backslash, percent, and underscore so they are treated as
    literals when passed to an ilike(..., escape="\\") call.
    """
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def ilike_condition(column, value: str):
    """Case-insensitive partial match condition for a column."""
    return column.ilike(f"%{escape_like(value)}%", escape="\\")


def unaccent_lower(value):
    """Lowercase and strip accents from a column or literal."""
    return func.immutable_unaccent(func.lower(value))


def unaccent_ilike_condition(column, value: str):
    """Accent- and case-insensitive partial match condition for a column."""
    return unaccent_lower(column).ilike(
        unaccent_lower(f"%{escape_like(value)}%"), escape="\\"
    )


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


async def _execute_full_query(
    db: AsyncSession,
    base_query,
    order_by,
    conditions: Sequence,
):
    """Apply conditions/order and run the query with no limit or offset.

    The unpaginated counterpart of ``_execute_paginated_query``, used by the
    export paths: they need the whole filtered set, and no total count since
    there are no pages to build.
    """
    for condition in conditions:
        base_query = base_query.where(condition)
    order_by_clauses = order_by if isinstance(order_by, (list, tuple)) else (order_by,)
    return await db.execute(base_query.order_by(*order_by_clauses))


async def execute_all(
    db: AsyncSession,
    base_query,
    order_by,
    conditions: Sequence = (),
) -> list:
    """Execute an unpaginated single-entity query and return every row.

    Same filtering and ordering semantics as ``execute_paginated``, without
    limit/offset — an export must return the complete filtered set in the same
    order the on-screen listing shows.

    ``base_query`` must select a single entity/column — its rows are unwrapped
    with ``.scalars()``.
    """
    result = await _execute_full_query(db, base_query, order_by, conditions)
    return result.scalars().all()


async def execute_all_rows(
    db: AsyncSession,
    base_query,
    order_by,
    conditions: Sequence = (),
) -> list:
    """Execute an unpaginated multi-column query and return every row.

    The ``execute_paginated_rows`` counterpart for exports: each row comes back
    as a raw ``Row`` tuple rather than unwrapped to a scalar.
    """
    result = await _execute_full_query(db, base_query, order_by, conditions)
    return result.all()


async def stream_all(
    db: AsyncSession,
    base_query,
    order_by,
    conditions: Sequence = (),
    chunk: int = _STREAM_CHUNK,
) -> AsyncIterator:
    """Yield every row matching ``conditions``, a server-side chunk at a time.

    ``selectin`` eager loaders stay safe here -- they are post-loaders issuing
    their own query per chunk, which asyncpg tolerates alongside the open
    cursor. ``subqueryload`` and ``joinedload`` against a collection are not
    compatible with ``yield_per``; SQLAlchemy raises if one is used.

    The caller's transaction must stay open for the whole iteration.
    """
    for condition in conditions:
        base_query = base_query.where(condition)
    order_by_clauses = order_by if isinstance(order_by, (list, tuple)) else (order_by,)
    query = base_query.order_by(*order_by_clauses)
    result = await db.stream(query.execution_options(yield_per=chunk))
    async for row in result.scalars():
        yield row


async def stream_all_rows(
    db: AsyncSession,
    base_query,
    order_by,
    conditions: Sequence = (),
    chunk: int = _STREAM_CHUNK,
) -> AsyncIterator:
    """Stream a multi-column query, yielding raw ``Row`` tuples.

    The ``execute_all_rows`` counterpart, for queries selecting an entity plus
    a computed value.
    """
    for condition in conditions:
        base_query = base_query.where(condition)
    order_by_clauses = order_by if isinstance(order_by, (list, tuple)) else (order_by,)
    query = base_query.order_by(*order_by_clauses)
    result = await db.stream(query.execution_options(yield_per=chunk))
    async for row in result:
        yield row


async def achunked(source: AsyncIterator, size: int) -> AsyncIterator[list]:
    """Group an async iterator into lists of at most ``size`` items.

    Lets a caller keep a per-batch bulk lookup (one extra query per batch)
    while still streaming, instead of collecting every id up front.
    """
    batch: list = []
    async for item in source:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


async def execute_count(
    db: AsyncSession,
    count_query,
    conditions: Sequence = (),
) -> int:
    """Return how many rows match ``conditions``, without fetching any.

    Exports use this to declare their size up front (``X-Export-Row-Count``),
    so a client can tell a complete download from a truncated one.
    """
    for condition in conditions:
        count_query = count_query.where(condition)
    return (await db.execute(count_query)).scalar_one()


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
