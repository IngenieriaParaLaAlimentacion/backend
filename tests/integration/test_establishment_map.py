from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import cast
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import status

pytestmark = pytest.mark.asyncio

MAP_URL = "/api/v1/establishments/map"
DASHBOARD_URL = "/api/v1/establishments/{establishment_id}/dashboard"


def _bmi(weight_kg: float, height_cm: float) -> float:
    return weight_kg / (height_cm / 100) ** 2


@dataclass
class Scenario:
    establishment_with_data: UUID
    establishment_without_data: UUID


@pytest_asyncio.fixture
async def scenario(app) -> Scenario:
    """Seed one establishment with a mixed nutritional status and one with
    no measurements at all.

    Subject BMIs reuse the values from test_establishment_dashboard.py's
    scenario (same fixed birth date, same measurement dates), which are
    already known to land in the "normal" and "severely_wasted" WHO bands
    for a 6-year-old -- giving a non-trivial, deterministic severity to
    compare against the individual dashboard.
    """
    from app.db.database import AsyncSessionLocal
    from app.domain.subject import Sex
    from app.domain.user import UserRole, UserStatus
    from app.models.auth.user import User
    from app.models.establishments.establishment import Establishment
    from app.models.measurements.measurement import Measurement
    from app.models.measurements.measurement_alert import MeasurementAlert
    from app.models.subjects.subject import Subject
    from app.reference_data.anthropometry import evaluate_alerts

    def _establishment(
        name: str, city: str, province: str, latitude: float, longitude: float
    ) -> Establishment:
        return Establishment(
            name=name,
            formatted_address=f"Calle {name}",
            latitude=latitude,
            longitude=longitude,
            place_id=f"place-{uuid4().hex[:8]}",
            city=city,
            province=province,
        )

    def _subject(dni: int, name: str, last_name: str) -> Subject:
        return Subject(
            dni=dni,
            sex=Sex.MALE,
            name=name,
            last_name=last_name,
            # Fixed birth date so both subjects are exactly 6 years old at
            # the measurement dates below, pinning the WHO z-score band.
            birth_date=date(2018, 1, 1),
            is_rural=False,
            is_indigenous=False,
        )

    async with AsyncSessionLocal() as session:
        est_with_data = _establishment(
            "Comedor Con Datos", "La Plata", "Buenos Aires", -34.9, -57.9
        )
        est_without_data = _establishment(
            "Comedor Sin Datos", "Cordoba", "Cordoba", -31.4, -64.2
        )
        worker = User(
            name="Pedro",
            last_name="Gomez",
            email=f"{uuid4()}@test.com",
            role=UserRole.FIELD_WORKER,
            status=UserStatus.ACTIVE,
        )
        subject_normal = _subject(20000001, "Hernan", "Normal")
        subject_severe = _subject(20000002, "Diego", "Severe")
        session.add_all(
            [est_with_data, est_without_data, worker, subject_normal, subject_severe]
        )
        await session.flush()

        pending_alerts = []
        for weight, height, subject, when in [
            (20.0, 118.0, subject_normal, datetime(2024, 6, 10)),
            (10.5, 120.0, subject_severe, datetime(2024, 6, 12)),
        ]:
            measured_at = when.replace(tzinfo=timezone.utc)
            bmi = _bmi(weight, height)
            measurement = Measurement(
                subject_id=subject.id,
                responsible_id=worker.id,
                establishment_id=est_with_data.id,
                weight_kg=weight,
                height_cm=height,
                bmi=bmi,
                measured_at=measured_at,
            )
            session.add(measurement)
            pending_alerts.append((measurement, bmi, subject, measured_at))

        await session.flush()

        for measurement, bmi, subject, measured_at in pending_alerts:
            for alert_type, severity, detail in evaluate_alerts(
                bmi=bmi,
                sex=subject.sex,
                birth_date=subject.birth_date,
                measured_at=measured_at,
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

        return Scenario(
            establishment_with_data=cast(UUID, est_with_data.id),
            establishment_without_data=cast(UUID, est_without_data.id),
        )


class TestMapAuth:
    async def test_unauthenticated_returns_401(self, client, scenario):
        response = await client.get(MAP_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_field_worker_is_forbidden(
        self, client, field_worker_headers, scenario
    ):
        response = await client.get(MAP_URL, headers=field_worker_headers)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_analyst_is_allowed(self, client, analyst_headers, scenario):
        response = await client.get(MAP_URL, headers=analyst_headers)
        assert response.status_code == status.HTTP_200_OK

    async def test_admin_is_allowed(self, client, admin_headers, scenario):
        response = await client.get(MAP_URL, headers=admin_headers)
        assert response.status_code == status.HTTP_200_OK


class TestMapContent:
    @pytest_asyncio.fixture
    async def body(self, client, admin_headers, scenario):
        response = await client.get(MAP_URL, headers=admin_headers)
        assert response.status_code == status.HTTP_200_OK
        return response.json()

    def _item(self, body, establishment_id: UUID) -> dict:
        return next(
            item
            for item in body["establishments"]
            if item["id"] == str(establishment_id)
        )

    async def test_returns_every_establishment_without_pagination(self, body):
        """CA 2: no pagination envelope, every seeded establishment in one shot."""
        assert body.keys() == {"establishments"}
        assert len(body["establishments"]) == 2

    async def test_item_shape_is_minimal(self, body, scenario):
        """CA 5: only what a map marker needs -- no ficha detail fields."""
        item = self._item(body, scenario.establishment_with_data)
        assert item.keys() == {
            "id",
            "name",
            "latitude",
            "longitude",
            "has_data",
            "severity",
            "dominant_status",
        }

    async def test_reports_identity_and_location(self, body, scenario):
        """CA 1: location travels alongside the status."""
        item = self._item(body, scenario.establishment_with_data)
        assert item["name"] == "Comedor Con Datos"
        assert item["latitude"] == pytest.approx(-34.9)
        assert item["longitude"] == pytest.approx(-57.9)

    async def test_establishment_without_measurements_is_present_not_omitted(
        self, body, scenario
    ):
        """CA 3: no data is explicit, never absent and never a fake normal."""
        item = self._item(body, scenario.establishment_without_data)
        assert item["has_data"] is False
        assert item["severity"] is None
        assert item["dominant_status"] is None

    async def test_severity_matches_the_individual_dashboard(
        self, client, admin_headers, body, scenario
    ):
        """CA 1 / CA 4: same severity criterion as the establishment ficha."""
        dashboard_response = await client.get(
            DASHBOARD_URL.format(establishment_id=scenario.establishment_with_data),
            headers=admin_headers,
        )
        alert_status = dashboard_response.json()["alert_status"]

        item = self._item(body, scenario.establishment_with_data)
        assert item["has_data"] is True
        assert item["severity"] == alert_status["severity"]
        assert item["dominant_status"] == alert_status["dominant_status"]
