import uuid
from datetime import date

import pytest
import pytest_asyncio
from fastapi import status

from app.core.security import create_access_token
from app.domain.user import UserRole

pytestmark = pytest.mark.asyncio

MEASUREMENTS_URL = "/api/v1/measurements"


@pytest_asyncio.fixture
async def db_adult_subject(app):
    """Insert an adult subject (born 1990) and return the ORM instance."""
    from app.db.database import AsyncSessionLocal
    from app.domain.subject import Sex
    from app.models.subjects.subject import Subject

    async with AsyncSessionLocal() as session:
        subject = Subject(
            dni=55555555,
            sex=Sex.MALE,
            name="Carlos",
            last_name="Lopez",
            birth_date=date(1990, 1, 1),
            is_rural=False,
            is_indigenous=False,
        )
        session.add(subject)
        await session.commit()
        await session.refresh(subject)
        return subject


@pytest_asyncio.fixture
async def db_admin_headers(app):
    """Create a real admin user in the DB and return auth headers."""
    from app.db.database import AsyncSessionLocal
    from app.domain.user import UserStatus
    from app.models.auth.user import User
    from app.models.auth.user import UserRole as ORMUserRole

    user_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        session.add(
            User(
                id=user_id,
                name="Admin",
                last_name="Test",
                email=f"{user_id}@test.com",
                role=ORMUserRole.ADMIN,
                status=UserStatus.ACTIVE,
            )
        )
        await session.commit()

    token = create_access_token(user_id, role=UserRole.ADMIN)
    return {"Authorization": f"Bearer {token}"}


def _body(subject_id, establishment_id, **overrides):
    return {
        "subject_id": str(subject_id),
        "establishment_id": str(establishment_id),
        "weight_kg": 70.0,
        "height_cm": 170.0,
        "measured_at": "2024-06-01T12:00:00Z",
        **overrides,
    }


async def _upload(client, subject_id, establishment_id, headers, **overrides):
    return await client.post(
        MEASUREMENTS_URL,
        json=_body(subject_id, establishment_id, **overrides),
        headers=headers,
    )


async def _upload_with_id(
    client, measurement_id, subject_id, establishment_id, headers, **overrides
):
    return await _upload(
        client,
        subject_id,
        establishment_id,
        headers,
        id=str(measurement_id),
        **overrides,
    )


class TestAuth:
    async def test_unauthenticated_returns_401(
        self, client, db_adult_subject, db_establishment
    ):
        response = await _upload(
            client,
            db_adult_subject.id,
            db_establishment.id,
            headers={},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_invalid_token_returns_401(
        self, client, db_adult_subject, db_establishment
    ):
        response = await _upload(
            client,
            db_adult_subject.id,
            db_establishment.id,
            headers={"Authorization": "Bearer not_a_valid_token"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestValidation:
    async def test_weight_below_minimum_returns_422(
        self, client, db_adult_subject, db_establishment, admin_headers
    ):
        response = await _upload(
            client,
            db_adult_subject.id,
            db_establishment.id,
            admin_headers,
            weight_kg=0.5,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_weight_above_maximum_returns_422(
        self, client, db_adult_subject, db_establishment, admin_headers
    ):
        response = await _upload(
            client,
            db_adult_subject.id,
            db_establishment.id,
            admin_headers,
            weight_kg=301.0,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_height_below_minimum_returns_422(
        self, client, db_adult_subject, db_establishment, admin_headers
    ):
        response = await _upload(
            client,
            db_adult_subject.id,
            db_establishment.id,
            admin_headers,
            height_cm=20.0,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_height_above_maximum_returns_422(
        self, client, db_adult_subject, db_establishment, admin_headers
    ):
        response = await _upload(
            client,
            db_adult_subject.id,
            db_establishment.id,
            admin_headers,
            height_cm=251.0,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_future_measured_at_returns_422(
        self, client, db_adult_subject, db_establishment, admin_headers
    ):
        response = await _upload(
            client,
            db_adult_subject.id,
            db_establishment.id,
            admin_headers,
            measured_at="2099-01-01T00:00:00Z",
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


class TestNotFound:
    async def test_unknown_subject_returns_404(
        self, client, db_establishment, db_admin_headers
    ):
        response = await _upload(
            client,
            uuid.uuid4(),
            db_establishment.id,
            db_admin_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_unknown_establishment_returns_404(
        self, client, db_adult_subject, db_admin_headers
    ):
        response = await _upload(
            client,
            db_adult_subject.id,
            uuid.uuid4(),
            db_admin_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestEstablishmentAccess:
    async def test_field_worker_without_relation_returns_403(
        self, client, db_adult_subject, db_establishment, field_worker_headers
    ):
        """A field worker with no relation to the establishment is forbidden."""
        response = await _upload(
            client,
            db_adult_subject.id,
            db_establishment.id,
            field_worker_headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_field_worker_with_pending_relation_returns_403(
        self, client, db_adult_subject, db_establishment, app
    ):
        """A field worker with a PENDING relation to the establishment is forbidden."""
        from app.db.database import AsyncSessionLocal
        from app.domain.establishment import UserEstablishmentStatus
        from app.domain.user import UserStatus
        from app.models.auth.user import User
        from app.models.auth.user import UserRole as ORMUserRole
        from app.models.auth.user_establishment import UserEstablishment

        user_id = uuid.uuid4()
        async with AsyncSessionLocal() as session:
            session.add(
                User(
                    id=user_id,
                    name="Pedro",
                    last_name="Pending",
                    email=f"{user_id}@test.com",
                    role=ORMUserRole.FIELD_WORKER,
                    status=UserStatus.ACTIVE,
                )
            )
            session.add(
                UserEstablishment(
                    user_id=user_id,
                    establishment_id=db_establishment.id,
                    status=UserEstablishmentStatus.PENDING,
                )
            )
            await session.commit()

        token = create_access_token(user_id, role=UserRole.FIELD_WORKER)
        headers = {"Authorization": f"Bearer {token}"}

        response = await _upload(
            client,
            db_adult_subject.id,
            db_establishment.id,
            headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_field_worker_with_approved_relation_returns_201(
        self, client, db_adult_subject, db_establishment, field_worker_with_access
    ):
        """A field worker with an APPROVED relation can upload a measurement."""
        headers, _ = field_worker_with_access
        response = await _upload(
            client,
            db_adult_subject.id,
            db_establishment.id,
            headers,
        )
        assert response.status_code == status.HTTP_201_CREATED


class TestHappyPath:
    async def test_returns_201_with_correct_shape(
        self, client, db_adult_subject, db_establishment, db_admin_headers
    ):
        response = await _upload(
            client,
            db_adult_subject.id,
            db_establishment.id,
            db_admin_headers,
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert "id" in data
        assert data["subject_id"] == str(db_adult_subject.id)
        assert data["establishment_id"] == str(db_establishment.id)
        assert data["weight_kg"] == 70.0
        assert data["height_cm"] == 170.0
        assert "bmi" in data
        assert "measured_at" in data
        assert "created_at" in data
        assert "alerts" in data

    async def test_bmi_is_computed_correctly(
        self, client, db_adult_subject, db_establishment, db_admin_headers
    ):
        response = await _upload(
            client,
            db_adult_subject.id,
            db_establishment.id,
            db_admin_headers,
            weight_kg=90.0,
            height_cm=180.0,
        )
        assert response.status_code == status.HTTP_201_CREATED
        expected_bmi = 90.0 / (1.80**2)
        # BMI is rounded to 2 decimals in the response payload.
        assert response.json()["bmi"] == round(expected_bmi, 2)

    async def test_client_supplied_id_is_used_as_pk(
        self, client, db_adult_subject, db_establishment, db_admin_headers
    ):
        """A client-supplied id becomes the measurement's primary key."""
        measurement_id = uuid.uuid4()
        response = await _upload_with_id(
            client,
            measurement_id,
            db_adult_subject.id,
            db_establishment.id,
            db_admin_headers,
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["id"] == str(measurement_id)

    async def test_same_id_replay_returns_200(
        self, client, db_adult_subject, db_establishment, db_admin_headers
    ):
        """Re-POSTing the same id is an idempotent replay returning 200."""
        measurement_id = uuid.uuid4()
        first = await _upload_with_id(
            client,
            measurement_id,
            db_adult_subject.id,
            db_establishment.id,
            db_admin_headers,
        )
        assert first.status_code == status.HTTP_201_CREATED
        second = await _upload_with_id(
            client,
            measurement_id,
            db_adult_subject.id,
            db_establishment.id,
            db_admin_headers,
        )
        assert second.status_code == status.HTTP_200_OK
        assert second.json() == first.json()

    async def test_missing_id_still_returns_201(
        self, client, db_adult_subject, db_establishment, db_admin_headers
    ):
        """Omitting id still creates a new measurement with a server-generated id."""
        response = await _upload(
            client,
            db_adult_subject.id,
            db_establishment.id,
            db_admin_headers,
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert "id" in response.json()

    async def test_different_ids_create_separate_records(
        self, client, db_adult_subject, db_establishment, db_admin_headers
    ):
        first = await _upload(
            client,
            db_adult_subject.id,
            db_establishment.id,
            db_admin_headers,
        )
        second = await _upload(
            client,
            db_adult_subject.id,
            db_establishment.id,
            db_admin_headers,
        )
        assert first.json()["id"] != second.json()["id"]


class TestAlerts:
    async def test_obese_adult_bmi_triggers_alert(
        self, client, db_adult_subject, db_establishment, db_admin_headers
    ):
        """BMI >= 30 for an adult (> 228 months) generates an OBESE alert."""
        # weight=90, height=170 → BMI ≈ 31.1
        response = await _upload(
            client,
            db_adult_subject.id,
            db_establishment.id,
            db_admin_headers,
            weight_kg=90.0,
            height_cm=170.0,
        )
        assert response.status_code == status.HTTP_201_CREATED
        alerts = response.json()["alerts"]
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "obese"
        assert alerts[0]["severity"] == "high"

    async def test_normal_bmi_produces_no_alerts(
        self, client, db_adult_subject, db_establishment, db_admin_headers
    ):
        """BMI in the normal range (18.5-24.9) produces no alerts."""
        # weight=70, height=175 → BMI ≈ 22.9
        response = await _upload(
            client,
            db_adult_subject.id,
            db_establishment.id,
            db_admin_headers,
            weight_kg=70.0,
            height_cm=175.0,
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["alerts"] == []

    async def test_idempotent_replay_does_not_duplicate_alerts(
        self, client, db_adult_subject, db_establishment, db_admin_headers
    ):
        """Replaying an id that triggered alerts returns the same alerts,
        not duplicates."""
        from sqlalchemy import select

        from app.db.database import AsyncSessionLocal
        from app.models.measurements.measurement_alert import (
            MeasurementAlert,
        )

        measurement_id = uuid.uuid4()
        await _upload_with_id(
            client,
            measurement_id,
            db_adult_subject.id,
            db_establishment.id,
            db_admin_headers,
            weight_kg=90.0,
            height_cm=170.0,
        )
        await _upload_with_id(
            client,
            measurement_id,
            db_adult_subject.id,
            db_establishment.id,
            db_admin_headers,
            weight_kg=90.0,
            height_cm=170.0,
        )

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(MeasurementAlert))
            rows = result.scalars().all()

        assert len(rows) == 1
