from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.recipes.recipe import RecipeRequestRecord, RecipeSelection
from app.utils.db import execute_paginated


class RecipeRepository:
    """Persist complete recommendation requests and serialize selections."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, request: RecipeRequestRecord) -> None:
        """Stage a request with its complete proposal snapshots."""
        self.db.add(request)
        await self.db.flush()

    async def get(
        self, request_id: UUID, *, lock: bool = False
    ) -> RecipeRequestRecord | None:
        """Read a request, optionally locking it until the transaction ends."""
        query = select(RecipeRequestRecord).where(RecipeRequestRecord.id == request_id)
        if lock:
            query = query.with_for_update()
        result = await self.db.execute(
            query.options(
                selectinload(RecipeRequestRecord.proposals),
                selectinload(RecipeRequestRecord.selection),
            ).execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def choose(self, selection: RecipeSelection) -> None:
        """Stage the choice; the caller must already hold the request lock."""
        self.db.add(selection)
        await self.db.flush()

    async def history(
        self, establishment_id: UUID, *, chosen_only: bool, limit: int, offset: int
    ) -> tuple[list[RecipeRequestRecord], int]:
        """Read paginated requests, optionally restricted to chosen requests."""
        conditions = [RecipeRequestRecord.establishment_id == establishment_id]
        if chosen_only:
            conditions.append(RecipeRequestRecord.selection.has())
        return await execute_paginated(
            self.db,
            select(RecipeRequestRecord).options(
                selectinload(RecipeRequestRecord.proposals),
                selectinload(RecipeRequestRecord.selection),
            ),
            select(func.count()).select_from(RecipeRequestRecord),
            (RecipeRequestRecord.created_at.desc(), RecipeRequestRecord.id.desc()),
            limit,
            offset,
            conditions,
        )

    async def lock_reuse_id(self, request_id: UUID) -> None:
        """Serialize concurrent creations of the same client-generated reuse id."""
        # A row lock cannot protect an id that has not been inserted yet.
        await self.db.execute(
            select(func.pg_advisory_xact_lock(request_id.int % (2**63)))
        )
