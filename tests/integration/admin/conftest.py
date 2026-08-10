import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from fastapi import status

import app.db.database as db_module
from app.core.security import create_access_token
from app.domain.establishment import EstablishmentRequestStatus
from app.domain.user import UserRole, UserStatus
from app.models.establishment_request import EstablishmentRequest
from app.models.user import User

ADMIN_USERS_URL = "/api/v1/admin/users"
ADMIN_USER_URL = "/api/v1/admin/users/{user_id}"
ADMIN_SUBJECTS_URL = "/api/v1/admin/subjects"
ADMIN_ESTABLISHMENT_REQUESTS_URL = "/api/v1/admin/establishment-requests"
REGISTER_FIELD_WORKER_URL = "/api/v1/auth/register/field-worker"
APPROVE_URL = "/api/v1/admin/field-worker/{user_id}/establishments/approve"
REJECT_URL = "/api/v1/admin/field-worker/{user_id}/establishments/reject"
REJECT_FIELD_WORKER_URL = "/api/v1/admin/field-worker/{user_id}/reject"
SUBJECTS_URL = "/api/v1/subjects"
INVITE_ADMIN_URL = "/api/v1/admin/invite-admin"


async def _make_list_request(client, *, headers=None):
    return await client.get(ADMIN_USERS_URL, headers=headers or {})


async def _make_list_establishment_requests_request(client, *, headers=None):
    return await client.get(ADMIN_ESTABLISHMENT_REQUESTS_URL, headers=headers or {})


async def _make_approve_request(client, *, headers=None):
    return await client.patch(
        APPROVE_URL.format(user_id=uuid.uuid4()),
        json={"establishment_ids": [str(uuid.uuid4())]},
        headers=headers or {},
    )


async def _make_reject_request(client, *, headers=None):
    return await client.patch(
        REJECT_URL.format(user_id=uuid.uuid4()),
        json={"establishment_ids": [str(uuid.uuid4())]},
        headers=headers or {},
    )


async def _make_reject_field_worker_request(client, *, headers=None):
    return await client.patch(
        REJECT_FIELD_WORKER_URL.format(user_id=uuid.uuid4()),
        headers=headers or {},
    )


@pytest.fixture(
    params=[
        pytest.param(_make_list_request, id="GET /admin/users"),
        pytest.param(
            _make_approve_request,
            id="PATCH /admin/field-worker/{id}/establishments/approve",
        ),
        pytest.param(
            _make_reject_request,
            id="PATCH /admin/field-worker/{id}/establishments/reject",
        ),
        pytest.param(
            _make_reject_field_worker_request,
            id="PATCH /admin/field-worker/{id}/reject",
        ),
        pytest.param(
            _make_list_establishment_requests_request,
            id="GET /admin/establishment-requests",
        ),
    ]
)
def any_admin_request(request):
    return request.param


@pytest_asyncio.fixture
async def registered_field_worker(client, db_establishment):
    """Register a field worker linked to the test establishment and return the response
    body."""
    response = await client.post(
        REGISTER_FIELD_WORKER_URL,
        json={
            "email": f"field_worker_{uuid.uuid4().hex[:6]}@test.com",
            "password": "Password123!",
            "name": "Test",
            "last_name": "Field Worker",
            "establishments": [str(db_establishment.id)],
        },
    )
    assert response.status_code == status.HTTP_201_CREATED
    user_data = response.json()
    # Mark email as verified so admin operations work
    async with db_module.AsyncSessionLocal() as session:
        user = await session.get(User, user_data["id"])
        user.is_email_verified = True
        await session.commit()
    return user_data


@pytest_asyncio.fixture
async def field_worker_headers(field_worker_user_id):
    token = create_access_token(field_worker_user_id, role=UserRole.FIELD_WORKER)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def field_worker_user_id(app):
    """Insert an active establishment field worker and return its UUID."""
    return await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)


@pytest_asyncio.fixture
async def non_field_worker_user_id(app):
    """Insert an active analyst user and return its UUID."""
    return await _insert_user(UserRole.ANALYST, UserStatus.ACTIVE)


async def _insert_user(
    role: UserRole,
    user_status: UserStatus,
    *,
    name: str = "Test",
    last_name: str = "User",
    email: str | None = None,
) -> uuid.UUID:
    user_id = uuid.uuid4()
    async with db_module.AsyncSessionLocal() as session:
        session.add(
            User(
                id=user_id,
                name=name,
                last_name=last_name,
                email=email or f"{user_id}@test.com",
                role=role,
                status=user_status,
                is_email_verified=True,
            )
        )
        await session.commit()
    return user_id


async def _insert_establishment_request(
    user_id: uuid.UUID,
    *,
    name: str = "Comedor Test",
    formatted_address: str = "Calle Test 123",
    city: str | None = "Buenos Aires",
    province: str | None = "Buenos Aires",
    request_status: EstablishmentRequestStatus = EstablishmentRequestStatus.PENDING,
    created_at: datetime | None = None,
) -> uuid.UUID:
    """Insert an EstablishmentRequest row for the given requester and return its id.

    ``created_at`` can be pinned explicitly so ordering tests don't depend on
    wall-clock timing between two inserts.
    """
    request_id = uuid.uuid4()
    async with db_module.AsyncSessionLocal() as session:
        request = EstablishmentRequest(
            id=request_id,
            user_id=user_id,
            name=name,
            formatted_address=formatted_address,
            city=city,
            province=province,
            status=request_status,
        )
        if created_at is not None:
            request.created_at = created_at
        session.add(request)
        await session.commit()
    return request_id


def _subject_body(**overrides):
    return {
        "dni": 12345678,
        "sex": "male",
        "name": "Juan",
        "last_name": "Perez",
        "birth_date": "2010-01-01",
        "is_rural": False,
        "is_indigenous": False,
        **overrides,
    }
