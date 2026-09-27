import uuid

import pytest_asyncio

from app.core.security import create_access_token
from app.domain.user import UserRole
from tests.integration.activity.helpers import (
    Foods,
)


@pytest_asyncio.fixture
async def field_worker_a(app, db_establishment, make_field_worker_with_access):
    return await make_field_worker_with_access(db_establishment.id)


@pytest_asyncio.fixture
async def field_worker_b(app, db_establishment, make_field_worker_with_access):
    return await make_field_worker_with_access(db_establishment.id)


@pytest_asyncio.fixture
async def survey_author(app):
    """Create a real DB admin user (surveys.created_by_id is a real FK)."""
    from app.db.database import AsyncSessionLocal
    from app.domain.user import UserStatus
    from app.models.auth.user import User
    from app.models.auth.user import UserRole as ORMUserRole

    user_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        session.add(
            User(
                id=user_id,
                name="Author",
                last_name="Admin",
                email=f"{user_id}@test.com",
                role=ORMUserRole.ADMIN,
                status=UserStatus.ACTIVE,
            )
        )
        await session.commit()
    token = create_access_token(user_id, role=UserRole.ADMIN)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def foods(app) -> Foods:
    """Seed two catalog foods with different base units.

    The catalog has no create endpoint — it is only ever populated by the seed
    script — so the rows go in directly. Two different base_units on purpose:
    the payload's `unit` must come from each line's own food, not from a
    constant.
    """
    from app.db.database import AsyncSessionLocal
    from app.domain.food_catalog import MeasurementUnit
    from app.models.food_catalog.food import Food
    from app.models.food_catalog.food_category import FoodCategory

    async with AsyncSessionLocal() as session:
        cereals = FoodCategory(code="cereales", name="Cereales")
        session.add(cereals)
        await session.flush()

        rice = Food(
            code="arroz",
            name="Arroz",
            category_id=cereals.id,
            base_unit=MeasurementUnit.KILOGRAMOS,
        )
        eggs = Food(
            code="huevo",
            name="Huevo",
            category_id=cereals.id,
            base_unit=MeasurementUnit.UNIDADES,
        )
        session.add_all([rice, eggs])
        await session.commit()
        return Foods(rice=rice.id, eggs=eggs.id)
