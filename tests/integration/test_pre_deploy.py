import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, func, select

import app.db.database as db_module
from alembic import command
from app.config.settings import settings
from app.domain.user import UserRole, UserStatus
from app.models.auth.user import User
from app.models.auth.user_password import UserPassword
from app.models.food_catalog.food import Food
from app.models.food_catalog.food_category import FoodCategory
from app.models.food_catalog.food_nutrient_value import FoodNutrientValue
from app.models.food_catalog.gapa_food_category import GapaFoodCategory
from app.models.food_catalog.nutrient import Nutrient
from seed_food_catalog import seed_food_catalog
from seed_superadmin import create_super_admin


def test_head_migration_downgrades_and_upgrades(postgres_url, app):
    """Exercise the head revision, including a head that merges two branches."""
    asyncpg_url = postgres_url.replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://", 1
    )
    original_url = settings.database_url
    engine = create_engine(postgres_url)
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()
    down_revision = script.get_revision(head).down_revision
    parents = down_revision if isinstance(down_revision, tuple) else (down_revision,)

    def revisions():
        with engine.connect() as connection:
            return set(
                connection.exec_driver_sql(
                    "SELECT version_num FROM alembic_version"
                ).scalars()
            )

    settings.database_url = asyncpg_url
    try:
        assert revisions() == {head}
        command.downgrade(config, parents[0])
        assert revisions() == set(parents)
        command.upgrade(config, "head")
        assert revisions() == {head}
    finally:
        command.upgrade(config, "head")
        settings.database_url = original_url
        engine.dispose()


@pytest.mark.asyncio
async def test_superadmin_seed_can_run_twice(app):
    await create_super_admin()
    await create_super_admin()

    async with db_module.AsyncSessionLocal() as session:
        users = (
            (
                await session.execute(
                    select(User).where(User.email == str(settings.seed_admin_email))
                )
            )
            .scalars()
            .all()
        )
        assert len(users) == 1
        passwords = (
            (
                await session.execute(
                    select(UserPassword).where(UserPassword.user_id == users[0].id)
                )
            )
            .scalars()
            .all()
        )

    assert users[0].role == UserRole.SUPERADMIN
    assert users[0].status == UserStatus.ACTIVE
    assert len(passwords) == 1


@pytest.mark.asyncio
async def test_food_catalog_seed_can_run_twice(app):
    models = (FoodCategory, GapaFoodCategory, Nutrient, Food, FoodNutrientValue)

    async def counts():
        async with db_module.AsyncSessionLocal() as session:
            return tuple(
                [
                    await session.scalar(select(func.count()).select_from(model))
                    for model in models
                ]
            )

    await seed_food_catalog()
    first = await counts()
    await seed_food_catalog()

    assert all(count > 0 for count in first)
    assert await counts() == first
