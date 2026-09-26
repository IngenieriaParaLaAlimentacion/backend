import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import status
from jose import jwt

from app.domain.user import UserRole
from tests.integration.conftest import make_token_for_role
from tests.integration.subjects.conftest import (
    SUBJECTS_URL,
    _make_establishment,
    _make_measurement,
    _make_subject,
    _subject_payload,
    _upload,
    _upload_with_id,
)


class TestUploadSubject:
    async def test_unauthenticated_returns_401(self, client):
        """No token provided should return 401."""
        response = await _upload(client)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_malformed_token_returns_401(self, client):
        """A non-JWT string as token should return 401."""
        response = await _upload(
            client, headers={"Authorization": "Bearer token_invalido"}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_token_signed_with_wrong_secret_returns_401(self, client):
        """A JWT signed with the wrong secret should return 401."""
        forged = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "role": "field_worker",
                "type": "access",
            },
            "wrong_secret",
            algorithm="HS256",
        )
        response = await _upload(client, headers={"Authorization": f"Bearer {forged}"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_admin_role_returns_201(self, client):
        """A valid token with admin role should return 201."""
        token = await make_token_for_role(UserRole.ADMIN)
        response = await _upload(client, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == status.HTTP_201_CREATED

    async def test_analyst_role_returns_201(self, client):
        """A valid token with analyst role should return 201."""
        token = await make_token_for_role(UserRole.ANALYST)
        response = await _upload(client, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == status.HTTP_201_CREATED

    async def test_valid_request_returns_201(self, client, field_worker_headers):
        """A well-formed request with a field worker token returns 201."""
        response = await _upload(client, field_worker_headers)
        assert response.status_code == status.HTTP_201_CREATED

    async def test_valid_request_returns_subject_data(
        self, client, field_worker_headers
    ):
        """Response body includes all submitted fields and a generated id."""
        response = await _upload(client, field_worker_headers)
        data = response.json()
        assert "id" in data
        assert data["dni"] == 12345678
        assert data["sex"] == "male"
        assert data["name"] == "Juan"
        assert data["last_name"] == "Perez"
        assert data["birth_date"] == "2010-01-01"
        assert data["is_rural"] is False
        assert data["is_indigenous"] is False

    async def test_duplicate_dni_returns_409(self, client, field_worker_headers):
        """A second subject with the same DNI returns 409 with the canonical subject."""
        first = (await _upload(client, field_worker_headers)).json()
        response = await _upload(client, field_worker_headers)
        assert response.status_code == status.HTTP_409_CONFLICT
        canonical = response.json()["canonical_subject"]
        assert canonical["id"] == first["id"]
        assert canonical["dni"] == first["dni"]

    async def test_client_supplied_id_is_used_as_pk(self, client, field_worker_headers):
        """A client-supplied id becomes the subject's primary key."""
        subject_id = uuid.uuid4()
        response = await _upload_with_id(client, field_worker_headers, subject_id)
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["id"] == str(subject_id)

        got = await client.get(
            f"{SUBJECTS_URL}/{subject_id}", headers=field_worker_headers
        )
        assert got.status_code == status.HTTP_200_OK
        assert got.json()["id"] == str(subject_id)

    async def test_same_id_replay_returns_200(self, client, field_worker_headers):
        """Re-POSTing the same id is an idempotent replay returning 200."""
        subject_id = uuid.uuid4()
        first = await _upload_with_id(client, field_worker_headers, subject_id)
        assert first.status_code == status.HTTP_201_CREATED
        second = await _upload_with_id(client, field_worker_headers, subject_id)
        assert second.status_code == status.HTTP_200_OK
        assert second.json() == first.json()

    async def test_dni_conflict_different_id_returns_409_with_canonical(
        self, client, field_worker_headers
    ):
        """Same DNI under a different id returns 409 carrying the canonical subject."""
        id_a = uuid.uuid4()
        id_b = uuid.uuid4()
        first = await _upload_with_id(client, field_worker_headers, id_a, dni=30111222)
        assert first.status_code == status.HTTP_201_CREATED
        response = await _upload_with_id(
            client, field_worker_headers, id_b, dni=30111222
        )
        assert response.status_code == status.HTTP_409_CONFLICT
        canonical = response.json()["canonical_subject"]
        assert canonical["id"] == str(id_a)
        assert canonical["dni"] == 30111222

    async def test_missing_id_still_returns_201(self, client, field_worker_headers):
        """Omitting id preserves the backoffice create path."""
        response = await _upload(client, field_worker_headers)
        assert response.status_code == status.HTTP_201_CREATED
        assert "id" in response.json()

    async def test_future_birth_date_returns_422(self, client, field_worker_headers):
        """A birthdate in the future is rejected with 422."""
        future = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
        response = await _upload(client, field_worker_headers, birth_date=future)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_dni_zero_returns_422(self, client, field_worker_headers):
        """DNI 0 is below the minimum allowed value."""
        response = await _upload(client, field_worker_headers, dni=0)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_dni_above_max_returns_422(self, client, field_worker_headers):
        """DNI above 99999999 exceeds the Argentine DNI range."""
        response = await _upload(client, field_worker_headers, dni=100000000)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_whitespace_name_returns_422(self, client, field_worker_headers):
        """A name composed only of whitespace is rejected after stripping."""
        response = await _upload(client, field_worker_headers, name="   ")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.parametrize(
        "field",
        ["dni", "sex", "name", "last_name", "birth_date", "is_rural", "is_indigenous"],
    )
    async def test_each_required_field_is_mandatory(
        self, client, field_worker_headers, field
    ):
        """Omitting any single required field returns 422."""
        body = _subject_payload()
        del body[field]
        response = await client.post(
            SUBJECTS_URL, json=body, headers=field_worker_headers
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


class TestGetSubject:
    async def test_returns_200_with_subject_data(self, client, field_worker_headers):
        """A subject that was just created can be retrieved by id."""
        created = (await _upload(client, field_worker_headers)).json()
        response = await client.get(
            f"{SUBJECTS_URL}/{created['id']}", headers=field_worker_headers
        )
        assert response.status_code == status.HTTP_200_OK
        # The detail view is a superset of the create response: it adds the
        # subject's latest measurement and its derived status.
        assert response.json().items() >= created.items()

    async def test_never_measured_subject_has_null_status(
        self, client, field_worker_headers
    ):
        """No measurement is not 'normal' -- both fields must come back null."""
        created = (await _upload(client, field_worker_headers)).json()
        body = (
            await client.get(
                f"{SUBJECTS_URL}/{created['id']}", headers=field_worker_headers
            )
        ).json()
        assert body["nutritional_status"] is None
        assert body["latest_measurement"] is None

    async def test_unknown_id_returns_404(self, client, field_worker_headers):
        """A random UUID that was never registered returns 404."""
        response = await client.get(
            f"{SUBJECTS_URL}/{uuid.uuid4()}", headers=field_worker_headers
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_unauthenticated_returns_401(self, client):
        """No token on GET should return 401."""
        response = await client.get(f"{SUBJECTS_URL}/{uuid.uuid4()}")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestGetSubjectLatestMeasurement:
    """The detail view carries the subject's latest reading across all
    establishments."""

    @pytest_asyncio.fixture
    async def measured_subject(self, app, field_worker_user_id):
        """Seed one subject measured twice, at two different establishments.

        The older reading is at "Comedor Viejo" and is severely wasted; the newer
        one is at "Comedor Nuevo" and is healthy. A per-establishment view of
        Comedor Viejo would report the subject as severely wasted, so this fixture
        pins down that the subject detail reports the global latest instead.
        """
        from app.db.database import AsyncSessionLocal
        from app.models.measurements.measurement_alert import (
            MeasurementAlert,
        )
        from app.reference_data.anthropometry import evaluate_alerts

        async with AsyncSessionLocal() as session:
            old_est = _make_establishment(
                "Comedor Viejo",
                "Calle 1",
                latitude=-34.9,
                longitude=-57.9,
                city="La Plata",
                province="Buenos Aires",
            )
            new_est = _make_establishment(
                "Comedor Nuevo",
                "Calle 2",
                latitude=-31.4,
                longitude=-64.2,
                city="Cordoba",
                province="Cordoba",
            )
            subject = _make_subject(71234567, "Nico", "Medido", date(2018, 1, 1))
            session.add_all([old_est, new_est, subject])
            await session.flush()

            created = []
            for weight, height, est, when in [
                (10.0, 120.0, old_est, datetime(2024, 1, 10, tzinfo=timezone.utc)),
                (20.0, 118.0, new_est, datetime(2024, 6, 10, tzinfo=timezone.utc)),
            ]:
                measurement = _make_measurement(
                    subject.id,
                    field_worker_user_id,
                    est.id,
                    weight_kg=weight,
                    height_cm=height,
                    measured_at=when,
                )
                session.add(measurement)
                created.append((measurement, measurement.bmi, when))

            await session.flush()
            for measurement, bmi, when in created:
                for alert_type, severity, detail in evaluate_alerts(
                    bmi=bmi,
                    sex=subject.sex,
                    birth_date=subject.birth_date,
                    measured_at=when,
                ):
                    session.add(
                        MeasurementAlert(
                            measurement_id=measurement.id,
                            alert_type=alert_type,
                            severity=severity,
                            detail=detail,
                        )
                    )
            await session.commit()
            return subject.id

    @pytest_asyncio.fixture
    async def body(self, client, field_worker_headers, measured_subject):
        response = await client.get(
            f"{SUBJECTS_URL}/{measured_subject}", headers=field_worker_headers
        )
        assert response.status_code == status.HTTP_200_OK
        return response.json()

    async def test_reports_the_most_recent_measurement(self, body):
        assert body["latest_measurement"]["measured_at"].startswith("2024-06-10")
        assert body["latest_measurement"]["weight_kg"] == 20.0

    async def test_latest_wins_across_establishments(self, body):
        # The superseded reading was taken at a different establishment and was
        # severely wasted; the global latest is the healthy one.
        assert body["latest_measurement"]["establishment"]["name"] == "Comedor Nuevo"
        assert body["nutritional_status"] == "normal"
        assert body["latest_measurement"]["alerts"] == []

    async def test_carries_the_establishment_reference(self, body):
        establishment = body["latest_measurement"]["establishment"]
        assert {"id", "name", "city", "province"} == establishment.keys()

    async def test_measurement_shape(self, body):
        assert {
            "id",
            "measured_at",
            "weight_kg",
            "height_cm",
            "bmi",
            "establishment",
            "alerts",
        } == body["latest_measurement"].keys()

    async def test_still_carries_the_plain_subject_fields(self, body):
        assert body["dni"] == 71234567
        assert body["last_name"] == "Medido"
        assert body["birth_date"] == "2018-01-01"


class TestUpdateSubject:
    async def test_returns_200_with_updated_data(self, client, field_worker_headers):
        """A valid PATCH returns 200 with the updated field reflected."""
        created = (await _upload(client, field_worker_headers)).json()
        response = await client.patch(
            f"{SUBJECTS_URL}/{created['id']}",
            json={"name": "Carlos"},
            headers=field_worker_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Carlos"

    async def test_partial_update_does_not_affect_other_fields(
        self, client, field_worker_headers
    ):
        """Fields not included in the request must remain unchanged."""
        created = (await _upload(client, field_worker_headers)).json()
        await client.patch(
            f"{SUBJECTS_URL}/{created['id']}",
            json={"name": "Carlos"},
            headers=field_worker_headers,
        )
        response = await client.get(
            f"{SUBJECTS_URL}/{created['id']}", headers=field_worker_headers
        )
        data = response.json()
        assert data["last_name"] == created["last_name"]
        assert data["dni"] == created["dni"]
        assert data["birth_date"] == created["birth_date"]
        assert data["is_rural"] == created["is_rural"]
        assert data["is_indigenous"] == created["is_indigenous"]

    async def test_unknown_id_returns_404(self, client, field_worker_headers):
        """Patching a subject that does not exist returns 404."""
        response = await client.patch(
            f"{SUBJECTS_URL}/{uuid.uuid4()}",
            json={"name": "Carlos"},
            headers=field_worker_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_duplicate_dni_returns_409(self, client, field_worker_headers):
        """Setting a DNI that already belongs to another subject returns 409."""
        await _upload(client, field_worker_headers, dni=11111111)
        second = (await _upload(client, field_worker_headers, dni=22222222)).json()
        response = await client.patch(
            f"{SUBJECTS_URL}/{second['id']}",
            json={"dni": 11111111},
            headers=field_worker_headers,
        )
        assert response.status_code == status.HTTP_409_CONFLICT

    async def test_empty_body_returns_400(self, client, field_worker_headers):
        """An empty body with no fields to update returns 400."""
        created = (await _upload(client, field_worker_headers)).json()
        response = await client.patch(
            f"{SUBJECTS_URL}/{created['id']}",
            json={},
            headers=field_worker_headers,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_update_birth_date_returns_200(self, client, field_worker_headers):
        """Updating birth_date succeeds and the event payload is persisted correctly."""
        created = (await _upload(client, field_worker_headers)).json()
        new_date = "2011-06-15"
        response = await client.patch(
            f"{SUBJECTS_URL}/{created['id']}",
            json={"birth_date": new_date},
            headers=field_worker_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["birth_date"] == new_date
