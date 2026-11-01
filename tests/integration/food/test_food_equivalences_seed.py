import csv
from decimal import Decimal
from pathlib import Path

REFERENCE_DATA = Path(__file__).parents[3] / "app" / "reference_data"


def _csv_equivalences() -> dict[tuple[str, str], tuple]:
    """The rows of food_equivalences.csv, keyed by (food code, kind)."""
    with open(
        REFERENCE_DATA / "food_equivalences.csv", newline="", encoding="utf-8"
    ) as f:
        return {
            (row["food_code"], row["kind"]): (
                Decimal(row["value"]),
                row["source"],
                row["source_ref"],
                row["match_type"],
            )
            for row in csv.DictReader(f)
        }


async def _stored_equivalences() -> dict[tuple[str, str], tuple]:
    """The stored equivalences, keyed like the CSV rows."""
    from sqlalchemy import select

    from app.db.database import AsyncSessionLocal
    from app.models.food_catalog.food import Food
    from app.models.food_catalog.food_equivalence import FoodEquivalence

    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(Food.code, FoodEquivalence).join(
                FoodEquivalence, FoodEquivalence.food_id == Food.id
            )
        )
        return {
            (code, equivalence.kind.value): (
                equivalence.value,
                equivalence.source,
                equivalence.source_ref,
                equivalence.match_type.value,
            )
            for code, equivalence in rows.all()
        }


async def test_seed_loads_every_csv_row_and_can_run_twice(app):
    """Seeding twice stores exactly the rows of the CSV, with no duplicates."""
    import seed_food_catalog as seed

    await seed.seed_food_catalog()
    await seed.seed_food_catalog()

    assert await _stored_equivalences() == _csv_equivalences()


async def test_seed_restores_a_value_changed_in_the_database(app):
    """Seeding again overwrites stored values with the ones in the CSV."""
    from sqlalchemy import update

    import seed_food_catalog as seed
    from app.db.database import AsyncSessionLocal
    from app.models.food_catalog.food_equivalence import FoodEquivalence

    await seed.seed_food_catalog()
    async with AsyncSessionLocal() as session:
        await session.execute(update(FoodEquivalence).values(value=Decimal("9.9999")))
        await session.commit()

    await seed.seed_food_catalog()

    assert await _stored_equivalences() == _csv_equivalences()
