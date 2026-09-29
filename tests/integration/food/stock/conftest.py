import uuid

import pytest_asyncio


@pytest_asyncio.fixture
async def other_establishment_id(app) -> uuid.UUID:
    """Insert a second establishment, distinct from ``db_establishment``."""
    from app.db.database import AsyncSessionLocal
    from app.models.establishments.establishment import Establishment

    async with AsyncSessionLocal() as session:
        other = Establishment(
            name="Ajeno",
            formatted_address="Calle 2",
            latitude=-34.6,
            longitude=-58.4,
            place_id=f"place-{uuid.uuid4()}",
            city="Buenos Aires",
            province="Buenos Aires",
        )
        session.add(other)
        await session.commit()
        return other.id
