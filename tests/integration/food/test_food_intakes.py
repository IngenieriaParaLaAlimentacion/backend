"""Schema-level tests for the food intake tables.

Rows are written through the repository and a real session rather than over HTTP.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, delete, text
from sqlalchemy.exc import DBAPIError, IntegrityError


@pytest_asyncio.fixture
async def responsible(app):
    """A field worker with no password row, so the only thing standing in the
    way of deleting them is a food intake's RESTRICT."""
    from app.db.database import AsyncSessionLocal
    from app.domain.user import UserRole, UserStatus
    from app.models.auth.user import User

    async with AsyncSessionLocal() as session:
        user = User(
            name="Lucia",
            last_name="Intake",
            email=f"{uuid.uuid4()}@test.com",
            role=UserRole.FIELD_WORKER,
            status=UserStatus.ACTIVE,
        )
        session.add(user)
        await session.commit()
        return user


def _build_intake(establishment_id, responsible_id, items, **overrides):
    """Build an unsaved FoodIntake with one FoodIntakeItem per (food_id, qty)."""
    from app.domain.food_intake import FoodIntakeOriginType, FoodIntakeSource
    from app.models.food_intakes.food_intake import FoodIntake
    from app.models.food_intakes.food_intake_item import FoodIntakeItem

    fields = {
        "establishment_id": establishment_id,
        "responsible_id": responsible_id,
        "occurred_at": datetime.now(timezone.utc),
        "source": FoodIntakeSource.MANUAL,
        "origin_type": FoodIntakeOriginType.OTHER,
        "is_recurring": False,
        **overrides,
    }
    intake = FoodIntake(**fields)
    intake.items = [
        FoodIntakeItem(food_id=food_id, quantity=quantity)
        for food_id, quantity in items
    ]
    return intake


async def _persist(intake):
    """Persist an intake through the repository and return its id."""
    from app.db.database import AsyncSessionLocal
    from app.repositories.food_intakes.food_intake_repository import (
        FoodIntakeRepository,
    )

    async with AsyncSessionLocal() as session:
        await FoodIntakeRepository(session).create(intake)
        await session.commit()
        return intake.id


async def _fetch(intake_id):
    from app.db.database import AsyncSessionLocal
    from app.repositories.food_intakes.food_intake_repository import (
        FoodIntakeRepository,
    )

    async with AsyncSessionLocal() as session:
        return await FoodIntakeRepository(session).get_by_id(intake_id)


class TestPersistence:
    @pytest.mark.parametrize(
        ("origin_type", "is_recurring"),
        [("MUNICIPAL_GOVERNMENT", True), ("OTHER", False)],
    )
    async def test_origin_and_recurrence_are_persisted(
        self, db_establishment, responsible, foods, origin_type, is_recurring
    ):
        from app.domain.food_intake import FoodIntakeOriginType

        origin = FoodIntakeOriginType[origin_type]
        intake_id = await _persist(
            _build_intake(
                db_establishment.id,
                responsible.id,
                [(foods.rice, Decimal("1"))],
                origin_type=origin,
                is_recurring=is_recurring,
            )
        )

        intake = await _fetch(intake_id)
        assert intake.origin_type == origin
        assert intake.is_recurring is is_recurring

    async def test_intake_groups_its_items(self, db_establishment, responsible, foods):
        intake_id = await _persist(
            _build_intake(
                db_establishment.id,
                responsible.id,
                [(foods.rice, Decimal("25.500")), (foods.eggs, Decimal("360"))],
                comments="Donación semanal",
            )
        )

        intake = await _fetch(intake_id)
        assert intake.comments == "Donación semanal"
        assert {item.food_id for item in intake.items} == {foods.rice, foods.eggs}
        quantities = {item.food_id: item.quantity for item in intake.items}
        assert quantities[foods.rice] == Decimal("25.500")
        assert quantities[foods.eggs] == Decimal("360.000")

    async def test_item_unit_comes_from_the_catalog(
        self, db_establishment, responsible, foods
    ):
        """The line carries no unit — it is the food's base_unit."""
        from app.domain.food_catalog import MeasurementUnit

        intake_id = await _persist(
            _build_intake(
                db_establishment.id,
                responsible.id,
                [(foods.rice, Decimal("10")), (foods.eggs, Decimal("30"))],
            )
        )

        intake = await _fetch(intake_id)
        units = {item.food_id: item.food.base_unit for item in intake.items}
        assert units[foods.rice] == MeasurementUnit.KILOGRAMOS
        assert units[foods.eggs] == MeasurementUnit.UNIDADES

    async def test_a_new_intake_has_matching_timestamps(
        self, db_establishment, responsible, foods
    ):
        """A correction moves updated_at; until then it tracks created_at."""
        intake_id = await _persist(
            _build_intake(
                db_establishment.id, responsible.id, [(foods.rice, Decimal("1"))]
            )
        )

        intake = await _fetch(intake_id)
        assert intake.updated_at == intake.created_at

    async def test_photo_source_is_persisted(
        self, db_establishment, responsible, foods
    ):
        from app.domain.food_intake import FoodIntakeSource

        intake_id = await _persist(
            _build_intake(
                db_establishment.id,
                responsible.id,
                [(foods.rice, Decimal("1"))],
                source=FoodIntakeSource.PHOTO,
            )
        )

        assert (await _fetch(intake_id)).source == FoodIntakeSource.PHOTO

    async def test_replaying_a_client_generated_id_is_rejected(
        self, db_establishment, responsible, foods
    ):
        """The offline sync path relies on this to detect a replay."""
        from app.exceptions.domain_exceptions import UniqueConstraintError

        intake_id = uuid.uuid4()
        await _persist(
            _build_intake(
                db_establishment.id,
                responsible.id,
                [(foods.rice, Decimal("1"))],
                id=intake_id,
            )
        )

        with pytest.raises(UniqueConstraintError):
            await _persist(
                _build_intake(
                    db_establishment.id,
                    responsible.id,
                    [(foods.eggs, Decimal("12"))],
                    id=intake_id,
                )
            )


class TestRetroactiveLoad:
    async def test_occurred_at_is_independent_of_created_at(
        self, db_establishment, responsible, foods
    ):
        """An intake loaded days after the delivery keeps both dates."""
        occurred_at = datetime.now(timezone.utc) - timedelta(days=5)

        intake_id = await _persist(
            _build_intake(
                db_establishment.id,
                responsible.id,
                [(foods.rice, Decimal("3"))],
                occurred_at=occurred_at,
            )
        )

        intake = await _fetch(intake_id)
        assert intake.occurred_at == occurred_at
        assert intake.created_at - intake.occurred_at >= timedelta(days=4)


class TestConstraints:
    @pytest.mark.parametrize("field", ["origin_type", "is_recurring"])
    async def test_intake_metadata_cannot_be_null(
        self, db_establishment, responsible, foods, field
    ):
        with pytest.raises(IntegrityError):
            await _persist(
                _build_intake(
                    db_establishment.id,
                    responsible.id,
                    [(foods.rice, Decimal("1"))],
                    **{field: None},
                )
            )

    async def test_origin_must_be_a_known_database_enum_value(
        self, db_establishment, responsible, foods
    ):
        with pytest.raises(DBAPIError):
            await _persist(
                _build_intake(
                    db_establishment.id,
                    responsible.id,
                    [(foods.rice, Decimal("1"))],
                    origin_type="unknown",
                )
            )

    async def test_non_positive_quantity_is_rejected(
        self, db_establishment, responsible, foods
    ):
        with pytest.raises(IntegrityError):
            await _persist(
                _build_intake(
                    db_establishment.id, responsible.id, [(foods.rice, Decimal("0"))]
                )
            )

    async def test_unknown_food_is_rejected(self, db_establishment, responsible, foods):
        """A bad item must surface as itself, not as a duplicate intake id."""
        with pytest.raises(IntegrityError):
            await _persist(
                _build_intake(
                    db_establishment.id, responsible.id, [(uuid.uuid4(), Decimal("1"))]
                )
            )

    async def test_deleting_an_intake_deletes_its_items_only(
        self, db_establishment, responsible, foods
    ):
        """Items cascade; the referenced catalog foods survive."""
        from sqlalchemy import func, select

        from app.db.database import AsyncSessionLocal
        from app.models.food_catalog.food import Food
        from app.models.food_intakes.food_intake import FoodIntake
        from app.models.food_intakes.food_intake_item import FoodIntakeItem

        intake_id = await _persist(
            _build_intake(
                db_establishment.id,
                responsible.id,
                [(foods.rice, Decimal("2")), (foods.eggs, Decimal("12"))],
            )
        )

        async with AsyncSessionLocal() as session:
            await session.execute(delete(FoodIntake).where(FoodIntake.id == intake_id))
            await session.commit()

            items = await session.execute(
                select(func.count()).select_from(FoodIntakeItem)
            )
            assert items.scalar_one() == 0
            remaining_foods = await session.execute(
                select(func.count()).select_from(Food)
            )
            assert remaining_foods.scalar_one() == 2

    async def test_referenced_food_cannot_be_deleted(
        self, db_establishment, responsible, foods
    ):
        from app.db.database import AsyncSessionLocal
        from app.models.food_catalog.food import Food

        await _persist(
            _build_intake(
                db_establishment.id, responsible.id, [(foods.rice, Decimal("2"))]
            )
        )

        async with AsyncSessionLocal() as session:
            with pytest.raises(IntegrityError):
                await session.execute(delete(Food).where(Food.id == foods.rice))
                await session.commit()

    async def test_responsible_user_cannot_be_deleted(
        self, db_establishment, responsible, foods
    ):
        from app.db.database import AsyncSessionLocal
        from app.models.auth.user import User

        await _persist(
            _build_intake(
                db_establishment.id, responsible.id, [(foods.rice, Decimal("2"))]
            )
        )

        async with AsyncSessionLocal() as session:
            with pytest.raises(IntegrityError):
                await session.execute(delete(User).where(User.id == responsible.id))
                await session.commit()

    async def test_establishment_cannot_be_deleted_until_its_intakes_are_gone(
        self, db_establishment, responsible, foods
    ):
        from app.db.database import AsyncSessionLocal
        from app.models.establishments.establishment import Establishment
        from app.models.food_intakes.food_intake import FoodIntake

        intake_id = await _persist(
            _build_intake(
                db_establishment.id, responsible.id, [(foods.rice, Decimal("2"))]
            )
        )

        async with AsyncSessionLocal() as session:
            with pytest.raises(IntegrityError):
                await session.execute(
                    delete(Establishment).where(Establishment.id == db_establishment.id)
                )
                await session.commit()

        # Control: RESTRICT is what blocked it, nothing else.
        async with AsyncSessionLocal() as session:
            await session.execute(delete(FoodIntake).where(FoodIntake.id == intake_id))
            await session.execute(
                delete(Establishment).where(Establishment.id == db_establishment.id)
            )
            await session.commit()


def test_migration_backfills_existing_rows_and_removes_columns_on_downgrade(
    postgres_url, monkeypatch
):
    """Exercise the revision against a disposable legacy intake table."""
    revision_path = (
        Path(__file__).resolve().parents[3]
        / "alembic/versions/e6a4f17c902b_add_food_intake_origin_and_recurrence.py"
    )
    spec = spec_from_file_location("intake_origin_revision", revision_path)
    assert spec is not None and spec.loader is not None
    revision = module_from_spec(spec)
    spec.loader.exec_module(revision)
    schema = f"test_intake_migration_{uuid.uuid4().hex}"
    intake_id = uuid.uuid4()
    engine = create_engine(postgres_url)

    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            conn.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            conn.exec_driver_sql("CREATE TABLE food_intakes (id uuid PRIMARY KEY)")
            conn.execute(
                text("INSERT INTO food_intakes (id) VALUES (:id)"), {"id": intake_id}
            )
            monkeypatch.setattr(
                revision, "op", Operations(MigrationContext.configure(conn))
            )

            revision.upgrade()

            row = conn.execute(
                text(
                    "SELECT origin_type::text, is_recurring "
                    "FROM food_intakes WHERE id = :id"
                ),
                {"id": intake_id},
            ).one()
            assert row == ("other", False)
            columns = conn.execute(
                text(
                    "SELECT column_name, is_nullable, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = 'food_intakes' "
                    "AND column_name IN ('origin_type', 'is_recurring')"
                ),
                {"schema": schema},
            ).all()
            actual_columns = {
                name: (nullable, default) for name, nullable, default in columns
            }
            assert actual_columns == {
                "origin_type": ("NO", None),
                "is_recurring": ("NO", None),
            }

            revision.downgrade()

            remaining_columns = (
                conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = :schema AND table_name = 'food_intakes'"
                    ),
                    {"schema": schema},
                )
                .scalars()
                .all()
            )
            assert remaining_columns == ["id"]
            enum_count = conn.execute(
                text(
                    "SELECT count(*) FROM pg_type t "
                    "JOIN pg_namespace n ON n.oid = t.typnamespace "
                    "WHERE n.nspname = :schema AND t.typname = 'foodintakeorigintype'"
                ),
                {"schema": schema},
            ).scalar_one()
            assert enum_count == 0

            revision.upgrade()
            backfilled_again = conn.execute(
                text(
                    "SELECT origin_type::text, is_recurring "
                    "FROM food_intakes WHERE id = :id"
                ),
                {"id": intake_id},
            ).one()
            assert backfilled_again == ("other", False)
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
    finally:
        engine.dispose()
