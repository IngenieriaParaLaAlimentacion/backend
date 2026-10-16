import pytest_asyncio

from app.domain.user import UserRole


@pytest_asyncio.fixture
async def admin_user(make_user_with_role):
    return await make_user_with_role(UserRole.ADMIN)


@pytest_asyncio.fixture
async def analyst_user(make_user_with_role):
    return await make_user_with_role(UserRole.ANALYST)


@pytest_asyncio.fixture
async def field_worker_without_access(make_user_with_role):
    return await make_user_with_role(UserRole.FIELD_WORKER)
