import csv
from pathlib import Path

REFERENCE_DATA = Path(__file__).parents[3] / "app" / "reference_data"


async def _seed_foods_and_groups() -> None:
    import seed_food_catalog as seed
    from app.db.unit_of_work import UnitOfWork

    async with UnitOfWork() as uow:
        category_ids = await seed.seed_food_categories(uow)
        gapa_ids = await seed.seed_gapa_food_categories(uow)
        await seed.seed_foods(uow, category_ids, gapa_ids)
        await uow.commit()


async def test_seed_links_each_food_to_its_csv_group_and_can_run_twice(app):
    from sqlalchemy import func, select

    from app.db.database import AsyncSessionLocal
    from app.models.food_catalog.food import Food
    from app.models.food_catalog.gapa_food_category import GapaFoodCategory

    await _seed_foods_and_groups()
    await _seed_foods_and_groups()

    with open(REFERENCE_DATA / "foods.csv", newline="", encoding="utf-8") as f:
        expected = {row["code"]: row["gapa_category"] for row in csv.DictReader(f)}
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(Food.code, GapaFoodCategory.code).outerjoin(
                GapaFoodCategory, Food.gapa_category_id == GapaFoodCategory.id
            )
        )
        stored = {food: group or "" for food, group in rows.all()}
        group_count = await session.scalar(
            select(func.count()).select_from(GapaFoodCategory)
        )

    assert stored == expected
    assert group_count == 6
