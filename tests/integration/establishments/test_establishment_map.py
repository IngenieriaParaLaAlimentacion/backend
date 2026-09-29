from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import cast
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import status

from tests.integration.helpers import bmi_for
from tests.integration.urls import DASHBOARD_URL

MAP_URL = "/api/v1/establishments/map"


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
            bmi = bmi_for(weight, height)
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


@dataclass
class MultiReadingScenario:
    superseded_here: UUID
    same_subject_elsewhere: UUID


@pytest_asyncio.fixture
async def multi_reading_scenario(app) -> MultiReadingScenario:
    """Seed one subject measured repeatedly and across two establishments.

    At ``superseded_here`` the subject has an older severely-wasted reading and
    a newer normal one, so only the latest-reading pick yields "normal". At
    ``same_subject_elsewhere`` the same subject has a single severely-wasted
    reading, so a partition that ignores the establishment would attribute the
    subject's overall latest (normal) reading there and lose that status.
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

    normal = (20.0, 118.0)
    severely_wasted = (10.5, 120.0)

    async with AsyncSessionLocal() as session:
        establishments = [
            Establishment(
                name=name,
                formatted_address=f"Calle {name}",
                latitude=latitude,
                longitude=longitude,
                place_id=f"place-{uuid4().hex[:8]}",
                city="La Plata",
                province="Buenos Aires",
            )
            for name, latitude, longitude in [
                ("Comedor Superado", -34.9, -57.9),
                ("Comedor Vecino", -34.8, -57.8),
            ]
        ]
        worker = User(
            name="Pedro",
            last_name="Gomez",
            email=f"{uuid4()}@test.com",
            role=UserRole.FIELD_WORKER,
            status=UserStatus.ACTIVE,
        )
        subject = Subject(
            dni=30000001,
            sex=Sex.MALE,
            name="Hernan",
            last_name="Repetido",
            birth_date=date(2018, 1, 1),
            is_rural=False,
            is_indigenous=False,
        )
        session.add_all([*establishments, worker, subject])
        await session.flush()
        superseded_here, same_subject_elsewhere = establishments

        for establishment, (weight, height), when in [
            (superseded_here, severely_wasted, datetime(2024, 5, 1)),
            (superseded_here, normal, datetime(2024, 6, 10)),
            (same_subject_elsewhere, severely_wasted, datetime(2024, 6, 1)),
        ]:
            measured_at = when.replace(tzinfo=timezone.utc)
            bmi = bmi_for(weight, height)
            measurement = Measurement(
                subject_id=subject.id,
                responsible_id=worker.id,
                establishment_id=establishment.id,
                weight_kg=weight,
                height_cm=height,
                bmi=bmi,
                measured_at=measured_at,
            )
            session.add(measurement)
            await session.flush()
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

        return MultiReadingScenario(
            superseded_here=cast(UUID, superseded_here.id),
            same_subject_elsewhere=cast(UUID, same_subject_elsewhere.id),
        )


class TestMapWithMultipleReadings:
    async def _map_item(self, client, headers, establishment_id: UUID) -> dict:
        response = await client.get(MAP_URL, headers=headers)
        assert response.status_code == status.HTTP_200_OK
        return next(
            item
            for item in response.json()["establishments"]
            if item["id"] == str(establishment_id)
        )

    async def _dashboard_alert_status(
        self, client, headers, establishment_id: UUID
    ) -> dict:
        response = await client.get(
            DASHBOARD_URL.format(establishment_id=establishment_id),
            headers=headers,
        )
        assert response.status_code == status.HTTP_200_OK
        return response.json()["alert_status"]

    async def test_latest_reading_supersedes_older_ones(
        self, client, admin_headers, multi_reading_scenario
    ):
        item = await self._map_item(
            client, admin_headers, multi_reading_scenario.superseded_here
        )
        assert item["dominant_status"] == "normal"

    async def test_subject_is_evaluated_independently_per_establishment(
        self, client, admin_headers, multi_reading_scenario
    ):
        item = await self._map_item(
            client, admin_headers, multi_reading_scenario.same_subject_elsewhere
        )
        assert item["has_data"] is True
        assert item["dominant_status"] == "severely_wasted"

    @pytest.mark.parametrize(
        "establishment", ["superseded_here", "same_subject_elsewhere"]
    )
    async def test_every_map_item_matches_its_dashboard(
        self, client, admin_headers, multi_reading_scenario, establishment
    ):
        establishment_id = getattr(multi_reading_scenario, establishment)
        alert_status = await self._dashboard_alert_status(
            client, admin_headers, establishment_id
        )
        item = await self._map_item(client, admin_headers, establishment_id)

        assert item["severity"] == alert_status["severity"]
        assert item["dominant_status"] == alert_status["dominant_status"]
