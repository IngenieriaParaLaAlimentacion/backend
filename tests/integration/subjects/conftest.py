import uuid
from datetime import date, datetime

import pytest_asyncio

from app.core.security import create_access_token
from app.domain.subject import Sex
from app.domain.user import UserRole, UserStatus
from app.models.establishment import Establishment
from app.models.measurement import Measurement
from app.models.subject import Subject
from app.models.user import User

SUBJECTS_URL = "/api/v1/subjects"


@pytest_asyncio.fixture
async def field_worker_user_id(app):
    # Imported here, not at module level: the `app` fixture repoints
    # AsyncSessionLocal at the test container's engine, and that patch only
    # takes effect once `app` has already run. A module-level import would
    # bind this name to the pre-patch (real) engine instead.
    from app.db.database import AsyncSessionLocal

    user_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        session.add(
            User(
                id=user_id,
                name="Test",
                last_name="Field Worker",
                email=f"{user_id}@test.com",
                role=UserRole.FIELD_WORKER,
                status=UserStatus.ACTIVE,
            )
        )
        await session.commit()
    return user_id


@pytest_asyncio.fixture
async def field_worker_headers(field_worker_user_id):
    token = create_access_token(field_worker_user_id, role=UserRole.FIELD_WORKER)
    return {"Authorization": f"Bearer {token}"}


def _subject_payload(**overrides):
    """Default JSON body for POST /subjects, with fields overridable per test."""
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


async def _upload(client, headers=None, **overrides):
    return await client.post(
        SUBJECTS_URL, json=_subject_payload(**overrides), headers=headers or {}
    )


async def _upload_with_id(client, headers, subject_id, **overrides):
    return await _upload(client, headers, id=str(subject_id), **overrides)


def _make_establishment(
    name: str,
    address: str,
    *,
    latitude: float,
    longitude: float,
    city: str,
    province: str,
) -> Establishment:
    """Build an unsaved Establishment with a unique place_id."""
    return Establishment(
        name=name,
        formatted_address=address,
        latitude=latitude,
        longitude=longitude,
        place_id=f"place-{uuid.uuid4().hex[:8]}",
        city=city,
        province=province,
    )


def _make_subject(
    dni: int,
    name: str,
    last_name: str,
    birth_date: date,
    *,
    sex: Sex = Sex.MALE,
    is_rural: bool = False,
    is_indigenous: bool = False,
) -> Subject:
    """Build an unsaved Subject."""
    return Subject(
        dni=dni,
        sex=sex,
        name=name,
        last_name=last_name,
        birth_date=birth_date,
        is_rural=is_rural,
        is_indigenous=is_indigenous,
    )


def _make_measurement(
    subject_id: uuid.UUID,
    responsible_id: uuid.UUID,
    establishment_id: uuid.UUID,
    *,
    weight_kg: float,
    height_cm: float,
    measured_at: datetime,
) -> Measurement:
    """Build an unsaved Measurement with its bmi derived from weight/height."""
    return Measurement(
        subject_id=subject_id,
        responsible_id=responsible_id,
        establishment_id=establishment_id,
        weight_kg=weight_kg,
        height_cm=height_cm,
        bmi=weight_kg / (height_cm / 100) ** 2,
        measured_at=measured_at,
    )
