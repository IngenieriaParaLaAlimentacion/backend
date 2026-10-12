import asyncio
import csv
import logging
import uuid
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from app.config.logging import setup_logging
from app.db.unit_of_work import UnitOfWork
from app.domain.food_catalog import MeasurementUnit, NutrientGroup
from app.models.food_catalog.food import Food
from app.models.food_catalog.food_category import FoodCategory
from app.models.food_catalog.food_nutrient_value import FoodNutrientValue
from app.models.food_catalog.gapa_food_category import GapaFoodCategory
from app.models.food_catalog.nutrient import Nutrient

setup_logging()
logger = logging.getLogger(__name__)

REFERENCE_DATA = Path(__file__).parent / "app" / "reference_data"


def _read_csv(name: str) -> list[dict]:
    with open(REFERENCE_DATA / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


async def seed_food_categories(uow: UnitOfWork) -> dict[str, UUID]:
    """Upsert food_categories by code, return {code: id}."""
    existing = {c.code: c for c in await uow.food_category_repo.get_all()}
    code_to_id: dict[str, UUID] = {}

    for row in _read_csv("food_categories.csv"):
        code = row["code"]
        category = existing.get(code)
        if category:
            category.name = row["name"]
            await uow.food_category_repo.update(category)
        else:
            category = FoodCategory(
                id=uuid.uuid4(),
                code=code,
                name=row["name"],
            )
            await uow.food_category_repo.create(category)
        code_to_id[code] = category.id

    logger.info(f"Seeded {len(code_to_id)} food categories")
    return code_to_id


async def seed_gapa_food_categories(uow: UnitOfWork) -> dict[str, UUID]:
    """Upsert gapa_food_categories by code, return {code: id}."""
    existing = {c.code: c for c in await uow.gapa_food_category_repo.get_all()}
    code_to_id: dict[str, UUID] = {}

    for row in _read_csv("gapa_food_categories.csv"):
        code = row["code"]
        category = existing.get(code)
        if category:
            category.name = row["name"]
            await uow.gapa_food_category_repo.update(category)
        else:
            category = GapaFoodCategory(
                id=uuid.uuid4(),
                code=code,
                name=row["name"],
            )
            await uow.gapa_food_category_repo.create(category)
        code_to_id[code] = category.id

    logger.info(f"Seeded {len(code_to_id)} GAPA food categories")
    return code_to_id


async def seed_nutrients(uow: UnitOfWork) -> dict[str, UUID]:
    """Upsert nutrients by code, return {code: id}."""
    existing = {n.code: n for n in await uow.nutrient_repo.get_all()}
    code_to_id: dict[str, UUID] = {}

    for row in _read_csv("nutrients.csv"):
        code = row["code"]
        nutrient = existing.get(code)
        if nutrient:
            nutrient.name = row["name"]
            nutrient.unit = row["unit"]
            nutrient.group = NutrientGroup(row["group"])
            await uow.nutrient_repo.update(nutrient)
        else:
            nutrient = Nutrient(
                id=uuid.uuid4(),
                code=code,
                name=row["name"],
                unit=row["unit"],
                group=NutrientGroup(row["group"]),
            )
            await uow.nutrient_repo.create(nutrient)
        code_to_id[code] = nutrient.id

    logger.info(f"Seeded {len(code_to_id)} nutrients")
    return code_to_id


async def seed_foods(
    uow: UnitOfWork,
    category_code_to_id: dict[str, UUID],
    gapa_category_code_to_id: dict[str, UUID],
) -> dict[str, UUID]:
    """Upsert foods by code, return {code: id}."""
    existing = {f.code: f for f in await uow.food_repo.get_all()}
    code_to_id: dict[str, UUID] = {}

    for row in _read_csv("foods.csv"):
        code = row["code"]
        category_id = category_code_to_id[row["category"]]
        # An empty cell means the food has no GAPA group.
        gapa_category_id = (
            gapa_category_code_to_id[row["gapa_category"]]
            if row["gapa_category"]
            else None
        )
        base_unit = MeasurementUnit(row["base_unit"])
        source_page = int(row["source_page"]) if row["source_page"] else None

        food = existing.get(code)
        if food:
            food.name = row["name"]
            food.category_id = category_id
            food.gapa_category_id = gapa_category_id
            food.base_unit = base_unit
            food.source_page = source_page
            await uow.food_repo.update(food)
        else:
            food = Food(
                id=uuid.uuid4(),
                code=code,
                name=row["name"],
                category_id=category_id,
                gapa_category_id=gapa_category_id,
                base_unit=base_unit,
                source_page=source_page,
            )
            await uow.food_repo.create(food)
        code_to_id[code] = food.id

    logger.info(f"Seeded {len(code_to_id)} foods")
    return code_to_id


async def seed_food_nutrient_values(
    uow: UnitOfWork,
    food_code_to_id: dict[str, UUID],
    nutrient_code_to_id: dict[str, UUID],
) -> None:
    """Upsert food_nutrient_values by (food_id, nutrient_id)."""
    existing = {
        (v.food_id, v.nutrient_id): v
        for v in await uow.food_nutrient_value_repo.get_all()
    }
    count = 0

    for row in _read_csv("food_nutrient_values.csv"):
        food_id = food_code_to_id[row["food_code"]]
        nutrient_id = nutrient_code_to_id[row["nutrient_code"]]
        amount = Decimal(row["amount_per_100g"])

        value = existing.get((food_id, nutrient_id))
        if value:
            value.amount_per_100g = amount
            await uow.food_nutrient_value_repo.update(value)
        else:
            value = FoodNutrientValue(
                id=uuid.uuid4(),
                food_id=food_id,
                nutrient_id=nutrient_id,
                amount_per_100g=amount,
            )
            await uow.food_nutrient_value_repo.create(value)
        count += 1

    logger.info(f"Seeded {count} food nutrient values")


async def seed_food_catalog() -> None:
    async with UnitOfWork() as uow:
        try:
            category_ids = await seed_food_categories(uow)
            gapa_category_ids = await seed_gapa_food_categories(uow)
            nutrient_ids = await seed_nutrients(uow)
            food_ids = await seed_foods(uow, category_ids, gapa_category_ids)
            await seed_food_nutrient_values(uow, food_ids, nutrient_ids)
            await uow.commit()
            logger.info("Food catalog seed complete")
        except Exception as error:
            logger.error(f"Error seeding food catalog: {error}")
            raise


if __name__ == "__main__":
    asyncio.run(seed_food_catalog())
