import uuid

import pytest_asyncio

from app.core.security import create_access_token
from app.domain.user import UserRole


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
