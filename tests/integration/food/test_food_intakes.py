"""Schema-level tests for the food intake tables.

Rows are written through the repository and a real session rather than over HTTP.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError


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
    from app.domain.food_intake import FoodIntakeSource
    from app.models.food_intakes.food_intake import FoodIntake
    from app.models.food_intakes.food_intake_item import FoodIntakeItem

    fields = {
        "establishment_id": establishment_id,
        "responsible_id": responsible_id,
        "occurred_at": datetime.now(timezone.utc),
        "source": FoodIntakeSource.MANUAL,
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
        """CA 2: the line carries no unit — it is the food's base_unit."""
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
        """CA 3: an intake loaded days after the delivery keeps both dates."""
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
        """CA 2: items cascade; the referenced catalog foods survive."""
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
