from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest_asyncio


@pytest_asyncio.fixture
async def catalog(app):
    """Two foods: ``leche`` in a GAPA group with calcium and protein, ``sal``
    with no group and calcium only."""
    from app.db.database import AsyncSessionLocal
    from app.domain.food_catalog import MeasurementUnit, NutrientGroup
    from app.models.food_catalog.food import Food
    from app.models.food_catalog.food_category import FoodCategory
    from app.models.food_catalog.food_nutrient_value import FoodNutrientValue
    from app.models.food_catalog.gapa_food_category import GapaFoodCategory
    from app.models.food_catalog.nutrient import Nutrient

    async with AsyncSessionLocal() as session:
        category = FoodCategory(code="varios", name="Varios")
        gapa = GapaFoodCategory(code="leche_yogur_y_quesos", name="Lácteos")
        calcium = Nutrient(
            code="calcio", name="Calcio", unit="mg", group=NutrientGroup.MINERAL
        )
        protein = Nutrient(
            code="proteinas",
            name="Proteínas",
            unit="g",
            group=NutrientGroup.MACRONUTRIENT,
        )
        session.add_all([category, gapa, calcium, protein])
        await session.flush()
        milk = Food(
            code="leche",
            name="Leche",
            category_id=category.id,
            gapa_category_id=gapa.id,
            base_unit=MeasurementUnit.LITROS,
        )
        salt = Food(
            code="sal",
            name="Sal",
            category_id=category.id,
            base_unit=MeasurementUnit.KILOGRAMOS,
        )
        session.add_all([milk, salt])
        await session.flush()
        session.add_all(
            [
                FoodNutrientValue(
                    food_id=milk.id, nutrient_id=calcium.id, amount_per_100g=120
                ),
                FoodNutrientValue(
                    food_id=milk.id, nutrient_id=protein.id, amount_per_100g=3
                ),
                FoodNutrientValue(
                    food_id=salt.id, nutrient_id=calcium.id, amount_per_100g=10
                ),
            ]
        )
        await session.commit()
        return {"milk": milk.id, "salt": salt.id}


async def test_get_with_nutrients_by_ids_loads_group_and_composition(catalog):
    from app.db.database import AsyncSessionLocal
    from app.repositories.food_catalog.food_repository import FoodRepository

    async with AsyncSessionLocal() as session:
        repo = FoodRepository(session)
        foods = await repo.get_with_nutrients_by_ids([catalog["milk"], catalog["salt"]])
        no_foods = await repo.get_with_nutrients_by_ids([])

    assert no_foods == []
    by_id = {food.id: food for food in foods}
    milk, salt = by_id[catalog["milk"]], by_id[catalog["salt"]]
    assert milk.gapa_category.code == "leche_yogur_y_quesos"
    assert {v.nutrient.code: v.amount_per_100g for v in milk.nutrient_values} == {
        "calcio": 120,
        "proteinas": 3,
    }
    assert salt.gapa_category is None


async def test_list_all_with_nutrients_returns_only_requested_nutrients(catalog):
    from app.db.database import AsyncSessionLocal
    from app.repositories.food_catalog.food_repository import FoodRepository

    async with AsyncSessionLocal() as session:
        repo = FoodRepository(session)
        rows = await repo.list_all_with_nutrients(["calcio"])
        no_rows = await repo.list_all_with_nutrients([])

    assert no_rows == []
    assert {
        (row.food_id, row.gapa_category_code, row.nutrient_code): row.amount_per_100g
        for row in rows
    } == {
        (catalog["milk"], "leche_yogur_y_quesos", "calcio"): 120,
        (catalog["salt"], None, "calcio"): 10,
    }


async def test_sum_quantities_by_food_adds_intakes_inside_the_window(
    foods, db_establishment, make_user_with_role
):
    from app.db.database import AsyncSessionLocal
    from app.domain.food_intake import FoodIntakeOriginType, FoodIntakeSource
    from app.domain.user import UserRole
    from app.models.food_intakes.food_intake import FoodIntake
    from app.models.food_intakes.food_intake_item import FoodIntakeItem
    from app.repositories.food_intakes.food_intake_repository import (
        FoodIntakeRepository,
    )

    _, responsible_id = await make_user_with_role(UserRole.FIELD_WORKER)

    def intake(when: datetime, items: list[tuple[UUID, str]]) -> FoodIntake:
        return FoodIntake(
            establishment_id=db_establishment.id,
            responsible_id=responsible_id,
            occurred_at=when,
            source=FoodIntakeSource.MANUAL,
            origin_type=FoodIntakeOriginType.OTHER,
            is_recurring=False,
            items=[
                FoodIntakeItem(food_id=food_id, quantity=Decimal(qty))
                for food_id, qty in items
            ],
        )

    start = datetime(2026, 3, 1, tzinfo=timezone.utc)
    mid = datetime(2026, 3, 15, tzinfo=timezone.utc)
    end = datetime(2026, 4, 1, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as session:
        session.add_all(
            [
                intake(start, [(foods.rice, "2.5"), (foods.eggs, "10")]),
                intake(mid, [(foods.rice, "1.5")]),
                # Just before the window and exactly at its end bound: both out.
                intake(start - timedelta(seconds=1), [(foods.rice, "1000")]),
                intake(end, [(foods.rice, "100")]),
            ]
        )
        await session.commit()

        totals = await FoodIntakeRepository(session).sum_quantities_by_food(
            db_establishment.id, start, end
        )

    assert totals == {foods.rice: Decimal("4"), foods.eggs: Decimal("10")}
