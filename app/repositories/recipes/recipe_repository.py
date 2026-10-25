from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.recipes.recipe import (
    RecipeProposalRecord,
    RecipeRequestRecord,
    RecipeSelection,
)
from app.utils.db import execute_paginated, execute_paginated_rows


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

    async def proposals(
        self, establishment_id: UUID, *, chosen_only: bool, limit: int, offset: int
    ):
        """Paginate individual proposals without loading every request's siblings."""
        chosen = (
            select(RecipeSelection.request_id)
            .where(
                RecipeSelection.request_id == RecipeRequestRecord.id,
                RecipeSelection.proposal_id == RecipeProposalRecord.id,
            )
            .correlate(RecipeRequestRecord, RecipeProposalRecord)
            .exists()
        )
        conditions = [RecipeRequestRecord.establishment_id == establishment_id]
        if chosen_only:
            conditions.append(chosen)
        join = RecipeRequestRecord.id == RecipeProposalRecord.request_id
        return await execute_paginated_rows(
            self.db,
            select(RecipeRequestRecord, RecipeProposalRecord, chosen).join(
                RecipeProposalRecord, join
            ),
            select(func.count())
            .select_from(RecipeRequestRecord)
            .join(RecipeProposalRecord, join),
            (
                RecipeRequestRecord.created_at.desc(),
                RecipeRequestRecord.id.desc(),
                RecipeProposalRecord.position.asc(),
            ),
            limit,
            offset,
            conditions,
        )
