from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.food_catalog import FoodListingParams, FoodSortOrder
from app.models.food_catalog.food import Food
from app.models.food_catalog.food_nutrient_value import FoodNutrientValue
from app.utils.db import execute_paginated, unaccent_ilike_condition, unaccent_lower

# Maps each FoodSortOrder value to its SQLAlchemy order clause.
# KeyError on an unmapped value is intentional: it surfaces missing cases immediately.
_SORT_CLAUSES = {
    FoodSortOrder.NAME_ASC: asc(func.lower(Food.name)),
    FoodSortOrder.NAME_DESC: desc(func.lower(Food.name)),
}


class FoodRepository:
    """Persistence operations for Food entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _listing_conditions(params: FoodListingParams) -> list:
        """Build the filter conditions for a food catalog listing."""
        conditions = []
        if params.search:
            conditions.append(unaccent_ilike_condition(Food.name, params.search))
        if params.category_id is not None:
            conditions.append(Food.category_id == params.category_id)
        return conditions

    @staticmethod
    def _search_order_clauses(term: str) -> list:
        """Rank matches by relevance: prefix matches first, then similarity."""
        normalized_name = unaccent_lower(Food.name)
        normalized_term = unaccent_lower(term)
        is_prefix_match = normalized_name.like(func.concat(normalized_term, "%"))
        return [
            desc(is_prefix_match),
            desc(func.similarity(normalized_name, normalized_term)),
            asc(func.lower(Food.name)),
        ]

    @staticmethod
    def _match_scores(term: str):
        """Trigram scores of ``foods.name`` against ``term``, accent/case-insensitive.

        ``word_similarity`` scores the catalog name against its best-matching
        extent of ``term``, so brand names and pack sizes elsewhere in a receipt
        line don't dilute the score the way whole-string ``similarity`` does --
        it's the primary signal. On its own, though, it's a poor filter for
        *short* catalog names (e.g. "Sal"): a short name can score deceptively
        high against a coincidental extent of unrelated text. Whole-string
        ``similarity`` is used as a second, independent floor -- a genuine match
        also carries non-trivial whole-string overlap, while a short spurious
        match doesn't (see ADR-0017).
        """
        normalized_name = unaccent_lower(Food.name)
        normalized_term = unaccent_lower(term)
        word_score = func.word_similarity(normalized_name, normalized_term)
        whole_score = func.similarity(normalized_name, normalized_term)
        return word_score, whole_score

    async def find_best_match(
        self, description: str, min_word_similarity: float, min_similarity: float
    ) -> Food | None:
        """Return the catalog food whose name best matches ``description``, or None.

        Used to auto-fill a receipt-extracted line's catalog reference (ADR-0017) -- a
        single best-or-nothing match, not a ranked candidate list. A food only
        qualifies once both scores from ``_match_scores`` clear their respective
        floor; among those, the highest ``word_similarity`` wins. No relations are
        eager-loaded: callers only need ``id``/``name``, mirroring ``get_by_ids``.
        """
        word_score, whole_score = self._match_scores(description)
        result = await self.db.execute(
            select(Food)
            .where(word_score >= min_word_similarity, whole_score >= min_similarity)
            .order_by(desc(word_score))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create(self, food: Food) -> Food:
        """Stage a new food for insertion."""
        self.db.add(food)
        return food

    async def update(self, food: Food) -> Food:
        """Persist changes made to an existing food."""
        await self.db.flush()
        return food

    async def list(
        self,
        limit: int,
        offset: int,
        params: FoodListingParams,
    ) -> tuple[list[Food], int]:
        """Return a paginated list of foods and the total matching count.

        ``category`` is eager-loaded via ``selectinload`` so the listing view
        can read the category ref without a per-row lookup.

        When ``params.search`` is set, results are ordered by relevance
        (prefix match, then similarity) and ``params.sort_order`` is ignored.
        """
        base_query = select(Food).options(selectinload(Food.category))
        count_query = select(func.count()).select_from(Food)
        order_by = (
            self._search_order_clauses(params.search)
            if params.search
            else _SORT_CLAUSES[params.sort_order]
        )
        foods, total = await execute_paginated(
            self.db,
            base_query,
            count_query,
            order_by,
            limit,
            offset,
            conditions=self._listing_conditions(params),
        )
        return foods, total

    async def get_by_id(self, food_id: UUID) -> Food | None:
        """Return a food with ``category`` and its full nutrient composition
        (``nutrient_values``, each with its ``nutrient``) loaded, or None.
        """
        result = await self.db.execute(
            select(Food)
            .where(Food.id == food_id)
            .options(
                selectinload(Food.category),
                selectinload(Food.nutrient_values).selectinload(
                    FoodNutrientValue.nutrient
                ),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_ids(self, food_ids: Iterable[UUID]) -> list[Food]:
        """Return the foods among ``food_ids`` that exist.

        Light on purpose — no nutrient composition — because callers use it to
        validate the food references of a movement, not to render a food.
        """
        ids = list(food_ids)
        if not ids:
            return []
        result = await self.db.execute(select(Food).where(Food.id.in_(ids)))
        return list(result.scalars().all())

    async def get_all(self) -> list[Food]:
        """Return every food.

        Seed-only: loads the full table into memory to build the upsert-by-code
        diff at container boot. Do not call from request-time code — use a
        paginated listing method instead.
        """
        result = await self.db.execute(select(Food))
        return list(result.scalars().all())
