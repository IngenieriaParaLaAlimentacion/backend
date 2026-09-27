from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import cast
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import status

DASHBOARD_URL = "/api/v1/establishments/{establishment_id}/dashboard"
SUBJECTS_URL = "/api/v1/establishments/{establishment_id}/subjects"
FIELD_WORKERS_URL = "/api/v1/establishments/{establishment_id}/field-workers"

MISSING_ID = UUID("00000000-0000-0000-0000-000000000000")


def _bmi(weight_kg: float, height_cm: float) -> float:
    return weight_kg / (height_cm / 100) ** 2


@dataclass
class Scenario:
    establishment_a: UUID  # the establishment under test
    establishment_b: UUID  # a second one, must never leak into A's numbers
    establishment_empty: UUID  # no measurements at all
    worker_approved: UUID  # Juan Gomez, 3 measurements at A
    worker_pending: UUID  # Rosa Pending, enrolled at A but not approved
    worker_rejected: UUID  # Rita Rejected, rejected at A
    worker_other: UUID  # Ana Diaz, approved at B only
    subject_normal: UUID  # Bruno Normal, 2 measurements at A (latest is normal)
    subject_wasted: UUID  # Clara Wasted, 1 measurement at A
    subject_severe: UUID  # Diego Severe, 1 measurement at A
    subject_elsewhere: UUID  # Elena Other, measured only at B


@pytest_asyncio.fixture
async def scenario(app) -> Scenario:
    """Seed two establishments, an empty one, workers, subjects and measurements.

    Subject BMIs are chosen so the WHO BMI-for-age z-score lands in a known
    band for a 6-year-old, giving a deterministic status distribution at
    establishment A: 1 normal, 1 wasted, 1 severely_wasted.
    """
    from app.db.database import AsyncSessionLocal
    from app.domain.establishment import UserEstablishmentStatus
    from app.domain.subject import Sex
    from app.domain.user import UserRole, UserStatus
    from app.models.auth.user import User
    from app.models.auth.user_establishment import UserEstablishment
    from app.models.establishments.establishment import Establishment
    from app.models.measurements.measurement import Measurement
    from app.models.measurements.measurement_alert import MeasurementAlert
    from app.models.subjects.subject import Subject
    from app.reference_data.anthropometry import evaluate_alerts

    def _establishment(name: str, city: str) -> Establishment:
        return Establishment(
            name=name,
            formatted_address=f"Calle {name}",
            latitude=-34.9,
            longitude=-57.9,
            place_id=f"place-{uuid4().hex[:8]}",
            city=city,
            province="Buenos Aires",
        )

    def _worker(name: str, last_name: str) -> User:
        return User(
            name=name,
            last_name=last_name,
            email=f"{uuid4()}@test.com",
            role=UserRole.FIELD_WORKER,
            status=UserStatus.ACTIVE,
        )

    def _subject(dni: int, name: str, last_name: str, sex: Sex) -> Subject:
        return Subject(
            dni=dni,
            sex=sex,
            name=name,
            last_name=last_name,
            # Fixed birth date so every subject is exactly 6 years old at the
            # measurement dates below, which pins the WHO z-score band.
            birth_date=date(2018, 1, 1),
            is_rural=False,
            is_indigenous=False,
        )

    async with AsyncSessionLocal() as session:
        est_a = _establishment("Comedor A", "La Plata")
        est_b = _establishment("Comedor B", "Cordoba")
        est_empty = _establishment("Comedor Vacio", "Rosario")

        w_approved = _worker("Juan", "Gomez")
        w_pending = _worker("Rosa", "Pending")
        w_rejected = _worker("Rita", "Rejected")
        w_other = _worker("Ana", "Diaz")

        s_normal = _subject(20000001, "Bruno", "Normal", Sex.MALE)
        s_wasted = _subject(20000002, "Clara", "Wasted", Sex.FEMALE)
        s_severe = _subject(20000003, "Diego", "Severe", Sex.MALE)
        s_elsewhere = _subject(20000004, "Elena", "Other", Sex.FEMALE)

        session.add_all(
            [
                est_a,
                est_b,
                est_empty,
                w_approved,
                w_pending,
                w_rejected,
                w_other,
                s_normal,
                s_wasted,
                s_severe,
                s_elsewhere,
            ]
        )
        await session.flush()

        session.add_all(
            [
                UserEstablishment(
                    user_id=w_approved.id,
                    establishment_id=est_a.id,
                    status=UserEstablishmentStatus.APPROVED,
                ),
                UserEstablishment(
                    user_id=w_pending.id,
                    establishment_id=est_a.id,
                    status=UserEstablishmentStatus.PENDING,
                ),
                UserEstablishment(
                    user_id=w_rejected.id,
                    establishment_id=est_a.id,
                    status=UserEstablishmentStatus.REJECTED,
                ),
                UserEstablishment(
                    user_id=w_other.id,
                    establishment_id=est_b.id,
                    status=UserEstablishmentStatus.APPROVED,
                ),
            ]
        )

        def _measure(subject, establishment, responsible, weight, height, measured_at):
            bmi = _bmi(weight, height)
            measurement = Measurement(
                subject_id=subject.id,
                responsible_id=responsible.id,
                establishment_id=establishment.id,
                weight_kg=weight,
                height_cm=height,
                bmi=bmi,
                measured_at=measured_at,
            )
            session.add(measurement)
            return measurement, bmi, subject

        pending_alerts = []
        for weight, height, subject, establishment, responsible, when in [
            # subject_normal: an early severely-wasted reading that must be
            # ignored, then a healthy one. This is what proves the averages and
            # the alert rollup use only the latest measurement per subject.
            (10.0, 120.0, s_normal, est_a, w_approved, datetime(2024, 1, 10)),
            (20.0, 118.0, s_normal, est_a, w_approved, datetime(2024, 6, 10)),
            (17.0, 118.0, s_wasted, est_a, w_approved, datetime(2024, 6, 11)),
            (10.5, 120.0, s_severe, est_a, w_other, datetime(2024, 6, 12)),
            (21.0, 119.0, s_elsewhere, est_b, w_other, datetime(2024, 6, 13)),
        ]:
            measured_at = when.replace(tzinfo=timezone.utc)
            measurement, bmi, subj = _measure(
                subject, establishment, responsible, weight, height, measured_at
            )
            pending_alerts.append((measurement, bmi, subj, measured_at))

        await session.flush()

        for measurement, bmi, subj, measured_at in pending_alerts:
            for alert_type, severity, detail in evaluate_alerts(
                bmi=bmi,
                sex=subj.sex,
                birth_date=subj.birth_date,
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
            establishment_a=cast(UUID, est_a.id),
            establishment_b=cast(UUID, est_b.id),
            establishment_empty=cast(UUID, est_empty.id),
            worker_approved=cast(UUID, w_approved.id),
            worker_pending=cast(UUID, w_pending.id),
            worker_rejected=cast(UUID, w_rejected.id),
            worker_other=cast(UUID, w_other.id),
            subject_normal=cast(UUID, s_normal.id),
            subject_wasted=cast(UUID, s_wasted.id),
            subject_severe=cast(UUID, s_severe.id),
            subject_elsewhere=cast(UUID, s_elsewhere.id),
        )


class TestDashboardAuth:
    async def test_unauthenticated_returns_401(self, client, scenario):
        response = await client.get(
            DASHBOARD_URL.format(establishment_id=scenario.establishment_a)
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_a_field_worker_without_access_is_forbidden(
        self, client, field_worker_headers, scenario
    ):
        """The role alone no longer decides: an approved relation does."""
        response = await client.get(
            DASHBOARD_URL.format(establishment_id=scenario.establishment_a),
            headers=field_worker_headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_a_field_worker_with_approved_access_is_allowed(
        self, client, make_field_worker_with_access, scenario
    ):
        headers, _ = await make_field_worker_with_access(scenario.establishment_a)

        response = await client.get(
            DASHBOARD_URL.format(establishment_id=scenario.establishment_a),
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK

    async def test_a_field_worker_cannot_read_another_establishment(
        self, client, make_field_worker_with_access, scenario
    ):
        """Approved at B does not open A."""
        headers, _ = await make_field_worker_with_access(scenario.establishment_b)

        response = await client.get(
            DASHBOARD_URL.format(establishment_id=scenario.establishment_a),
            headers=headers,
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_analyst_is_allowed(self, client, analyst_headers, scenario):
        response = await client.get(
            DASHBOARD_URL.format(establishment_id=scenario.establishment_a),
            headers=analyst_headers,
        )
        assert response.status_code == status.HTTP_200_OK

    async def test_admin_is_allowed(self, client, admin_headers, scenario):
        response = await client.get(
            DASHBOARD_URL.format(establishment_id=scenario.establishment_a),
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_200_OK

    @pytest.mark.parametrize("url", [DASHBOARD_URL, SUBJECTS_URL, FIELD_WORKERS_URL])
    async def test_unknown_establishment_returns_404(self, client, admin_headers, url):
        response = await client.get(
            url.format(establishment_id=MISSING_ID), headers=admin_headers
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.parametrize("url", [SUBJECTS_URL, FIELD_WORKERS_URL])
    async def test_listings_forbid_field_workers(
        self, client, field_worker_headers, scenario, url
    ):
        response = await client.get(
            url.format(establishment_id=scenario.establishment_a),
            headers=field_worker_headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestMetrics:
    @pytest_asyncio.fixture
    async def body(self, client, admin_headers, scenario):
        response = await client.get(
            DASHBOARD_URL.format(establishment_id=scenario.establishment_a),
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        return response.json()

    async def test_identifies_the_establishment(self, body):
        assert body["establishment"]["name"] == "Comedor A"
        assert body["establishment"]["city"] == "La Plata"
        assert body["establishment"]["province"] == "Buenos Aires"

    async def test_counts_only_subjects_measured_here(self, body):
        assert body["has_data"] is True
        # Elena was measured at establishment B only.
        assert body["metrics"]["subject_count"] == 3

    async def test_measurement_count_includes_history(self, body):
        # Bruno has two measurements at A; Clara and Diego one each.
        assert body["metrics"]["measurement_count"] == 4

    async def test_averages_use_only_the_latest_measurement_per_subject(self, body):
        # Bruno's superseded reading was 10.0 kg / 120.0 cm. Averaging every
        # measurement instead would drag the weight down to 14.25.
        expected_weight = round((20.0 + 17.0 + 10.5) / 3, 2)
        expected_height = round((118.0 + 118.0 + 120.0) / 3, 2)
        metrics = body["metrics"]
        assert metrics["avg_weight_kg"] == pytest.approx(expected_weight, abs=0.01)
        assert metrics["avg_height_cm"] == pytest.approx(expected_height, abs=0.01)

    async def test_avg_bmi_matches_latest_measurements(self, body):
        expected = round(
            (_bmi(20.0, 118.0) + _bmi(17.0, 118.0) + _bmi(10.5, 120.0)) / 3, 2
        )
        assert body["metrics"]["avg_bmi"] == pytest.approx(expected, abs=0.01)

    async def test_avg_age_is_age_at_measurement(self, body):
        # Every subject was born 2018-01-01 and measured in mid-2024: ~77 months.
        assert body["metrics"]["avg_age_months"] == 77

    async def test_last_measured_at_is_the_most_recent(self, body):
        assert body["metrics"]["last_measured_at"].startswith("2024-06-12")


class TestEmptyEstablishment:
    """CA 6: an establishment with no data must read as absent, not as zero."""

    @pytest_asyncio.fixture
    async def body(self, client, admin_headers, scenario):
        response = await client.get(
            DASHBOARD_URL.format(establishment_id=scenario.establishment_empty),
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        return response.json()

    async def test_has_data_is_false(self, body):
        assert body["has_data"] is False

    async def test_averages_are_null_not_zero(self, body):
        metrics = body["metrics"]
        assert metrics["avg_bmi"] is None
        assert metrics["avg_height_cm"] is None
        assert metrics["avg_weight_kg"] is None
        assert metrics["avg_age_months"] is None
        assert metrics["last_measured_at"] is None

    async def test_counts_are_zero(self, body):
        assert body["metrics"]["subject_count"] == 0
        assert body["metrics"]["measurement_count"] == 0

    async def test_alert_status_is_empty(self, body):
        alert_status = body["alert_status"]
        assert alert_status["severity"] is None
        assert alert_status["dominant_status"] is None
        assert alert_status["distribution"] == []
        assert alert_status["at_risk_percentage"] is None

    async def test_still_identifies_the_establishment(self, body):
        assert body["establishment"]["name"] == "Comedor Vacio"

    async def test_subject_listing_is_empty(self, client, admin_headers, scenario):
        response = await client.get(
            SUBJECTS_URL.format(establishment_id=scenario.establishment_empty),
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 0

    async def test_movement_dates_are_null_when_nothing_moved(self, body):
        assert body["metrics"]["last_intake_at"] is None
        assert body["metrics"]["last_outflow_at"] is None


class TestFoodMovementDates:
    """CA 5: the last intake and outflow dates, independent of measurements."""

    @pytest_asyncio.fixture
    async def rice(self, app) -> UUID:
        """Seed one catalog food to move."""
        from app.db.database import AsyncSessionLocal
        from app.domain.food_catalog import MeasurementUnit
        from app.models.food_catalog.food import Food
        from app.models.food_catalog.food_category import FoodCategory

        async with AsyncSessionLocal() as session:
            category = FoodCategory(code="cereales", name="Cereales")
            session.add(category)
            await session.flush()
            food = Food(
                code="arroz",
                name="Arroz",
                category_id=category.id,
                base_unit=MeasurementUnit.KILOGRAMOS,
            )
            session.add(food)
            await session.commit()
            return cast(UUID, food.id)

    @pytest_asyncio.fixture
    async def seeded(self, client, make_field_worker_with_access, scenario, rice):
        """Load food into the establishment that has no subjects at all.

        Deliberately the empty one: the metrics short-circuit on a zero subject
        count, and these two dates must survive it.
        """
        headers, _ = await make_field_worker_with_access(scenario.establishment_empty)
        await client.post(
            "/api/v1/food-intakes",
            json={
                "establishment_id": str(scenario.establishment_empty),
                "occurred_at": "2026-09-01T10:00:00Z",
                "items": [{"food_id": str(rice), "quantity": "10"}],
            },
            headers=headers,
        )
        await client.post(
            "/api/v1/food-intakes",
            json={
                "establishment_id": str(scenario.establishment_empty),
                "occurred_at": "2026-09-05T10:00:00Z",
                "items": [{"food_id": str(rice), "quantity": "5"}],
            },
            headers=headers,
        )
        await client.post(
            "/api/v1/food-outflows",
            json={
                "establishment_id": str(scenario.establishment_empty),
                "occurred_at": "2026-09-03T10:00:00Z",
                "items": [{"food_id": str(rice), "quantity": "4"}],
            },
            headers=headers,
        )
        return headers

    async def test_reports_the_most_recent_of_each_direction(
        self, client, admin_headers, scenario, seeded
    ):
        response = await client.get(
            DASHBOARD_URL.format(establishment_id=scenario.establishment_empty),
            headers=admin_headers,
        )

        metrics = response.json()["metrics"]
        assert metrics["last_intake_at"] == "2026-09-05T10:00:00Z"
        assert metrics["last_outflow_at"] == "2026-09-03T10:00:00Z"

    async def test_they_survive_the_no_subjects_short_circuit(
        self, client, admin_headers, scenario, seeded
    ):
        """`has_data` speaks of measurements, not of food."""
        response = await client.get(
            DASHBOARD_URL.format(establishment_id=scenario.establishment_empty),
            headers=admin_headers,
        )

        body = response.json()
        assert body["has_data"] is False
        assert body["metrics"]["subject_count"] == 0
        assert body["metrics"]["last_intake_at"] is not None


class TestAlertStatus:
    @pytest_asyncio.fixture
    async def alert_status(self, client, admin_headers, scenario):
        response = await client.get(
            DASHBOARD_URL.format(establishment_id=scenario.establishment_a),
            headers=admin_headers,
        )
        return response.json()["alert_status"]

    async def test_distribution_covers_every_subject(self, alert_status):
        assert alert_status["total_evaluated"] == 3
        assert sum(e["count"] for e in alert_status["distribution"]) == 3

    async def test_percentages_sum_to_one_hundred(self, alert_status):
        total = sum(e["percentage"] for e in alert_status["distribution"])
        assert total == pytest.approx(100.0, abs=0.05)

    async def test_expected_statuses_are_present(self, alert_status):
        by_status = {e["status"]: e for e in alert_status["distribution"]}
        assert set(by_status) == {"normal", "wasted", "severely_wasted"}
        assert by_status["normal"]["count"] == 1
        assert by_status["wasted"]["count"] == 1
        assert by_status["severely_wasted"]["count"] == 1

    async def test_severity_is_the_worst_present(self, alert_status):
        assert alert_status["severity"] == "critical"

    async def test_at_risk_excludes_normal_subjects(self, alert_status):
        assert alert_status["at_risk_count"] == 2
        assert alert_status["at_risk_percentage"] == pytest.approx(66.67, abs=0.01)

    async def test_normal_status_carries_no_severity(self, alert_status):
        normal = next(
            e for e in alert_status["distribution"] if e["status"] == "normal"
        )
        assert normal["severity"] is None

    async def test_all_normal_establishment_reports_no_severity(
        self, client, admin_headers, scenario
    ):
        # Establishment B holds a single subject with a healthy BMI.
        response = await client.get(
            DASHBOARD_URL.format(establishment_id=scenario.establishment_b),
            headers=admin_headers,
        )
        alert_status = response.json()["alert_status"]
        assert alert_status["dominant_status"] == "normal"
        assert alert_status["severity"] is None
        assert alert_status["at_risk_count"] == 0


class TestSubjectListing:
    @pytest_asyncio.fixture
    async def body(self, client, admin_headers, scenario):
        response = await client.get(
            SUBJECTS_URL.format(establishment_id=scenario.establishment_a),
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        return response.json()

    async def test_returns_the_paginated_envelope(self, body):
        assert {
            "items",
            "total",
            "page",
            "page_size",
            "total_pages",
        } <= body.keys()

    async def test_lists_only_subjects_of_this_establishment(self, body):
        assert body["total"] == 3
        assert {item["last_name"] for item in body["items"]} == {
            "Normal",
            "Wasted",
            "Severe",
        }

    async def test_items_carry_the_general_listing_fields(self, body):
        item = body["items"][0]
        assert {"id", "dni", "name", "last_name", "sex"} <= item.keys()

    async def test_items_are_enriched(self, body):
        item = body["items"][0]
        assert {
            "birth_date",
            "age_months",
            "measurement_count",
            "nutritional_status",
            "latest_measurement",
        } <= item.keys()
        assert {
            "id",
            "measured_at",
            "weight_kg",
            "height_cm",
            "bmi",
            "alerts",
        } == item["latest_measurement"].keys()

    async def test_latest_measurement_supersedes_older_ones(self, body):
        bruno = next(i for i in body["items"] if i["last_name"] == "Normal")
        assert bruno["measurement_count"] == 2
        assert bruno["latest_measurement"]["weight_kg"] == 20.0
        assert bruno["nutritional_status"] == "normal"
        assert bruno["latest_measurement"]["alerts"] == []

    async def test_nutritional_status_reflects_alerts(self, body):
        diego = next(i for i in body["items"] if i["last_name"] == "Severe")
        assert diego["nutritional_status"] == "severely_wasted"
        assert diego["latest_measurement"]["alerts"][0]["severity"] == "critical"

    async def test_search_by_name(self, client, admin_headers, scenario):
        response = await client.get(
            SUBJECTS_URL.format(establishment_id=scenario.establishment_a),
            headers=admin_headers,
            params={"search": "clara"},
        )
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["last_name"] == "Wasted"

    async def test_search_by_dni(self, client, admin_headers, scenario):
        response = await client.get(
            SUBJECTS_URL.format(establishment_id=scenario.establishment_a),
            headers=admin_headers,
            params={"search": "20000003"},
        )
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["last_name"] == "Severe"

    async def test_search_cannot_reach_other_establishments(
        self, client, admin_headers, scenario
    ):
        response = await client.get(
            SUBJECTS_URL.format(establishment_id=scenario.establishment_a),
            headers=admin_headers,
            params={"search": "Elena"},
        )
        assert response.json()["total"] == 0

    @pytest.mark.parametrize(
        "sort_order",
        [
            "measured_at_desc",
            "measured_at_asc",
            "name_asc",
            "name_desc",
            "bmi_desc",
            "bmi_asc",
            "age_desc",
            "age_asc",
        ],
    )
    async def test_every_sort_order_is_accepted(
        self, client, admin_headers, scenario, sort_order
    ):
        response = await client.get(
            SUBJECTS_URL.format(establishment_id=scenario.establishment_a),
            headers=admin_headers,
            params={"sort_order": sort_order},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 3

    async def test_name_asc_orders_by_last_name(self, client, admin_headers, scenario):
        response = await client.get(
            SUBJECTS_URL.format(establishment_id=scenario.establishment_a),
            headers=admin_headers,
            params={"sort_order": "name_asc"},
        )
        names = [item["last_name"] for item in response.json()["items"]]
        assert names == ["Normal", "Severe", "Wasted"]

    async def test_bmi_desc_orders_by_latest_bmi(self, client, admin_headers, scenario):
        response = await client.get(
            SUBJECTS_URL.format(establishment_id=scenario.establishment_a),
            headers=admin_headers,
            params={"sort_order": "bmi_desc"},
        )
        bmis = [i["latest_measurement"]["bmi"] for i in response.json()["items"]]
        assert bmis == sorted(bmis, reverse=True)

    async def test_pagination_slices_the_result(self, client, admin_headers, scenario):
        response = await client.get(
            SUBJECTS_URL.format(establishment_id=scenario.establishment_a),
            headers=admin_headers,
            params={"page": 2, "page_size": 2, "sort_order": "name_asc"},
        )
        body = response.json()
        assert body["total"] == 3
        assert body["total_pages"] == 2
        assert len(body["items"]) == 1
        assert body["items"][0]["last_name"] == "Wasted"


class TestFieldWorkerListing:
    @pytest_asyncio.fixture
    async def body(self, client, admin_headers, scenario):
        response = await client.get(
            FIELD_WORKERS_URL.format(establishment_id=scenario.establishment_a),
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        return response.json()

    async def test_defaults_to_approved_enrollments(self, body):
        assert body["total"] == 1
        assert body["items"][0]["last_name"] == "Gomez"
        assert body["items"][0]["relation_status"] == "approved"

    async def test_items_carry_identity_and_status(self, body):
        item = body["items"][0]
        assert {
            "id",
            "name",
            "last_name",
            "email",
            "user_status",
            "relation_status",
            "measurement_count",
            "last_measured_at",
        } <= item.keys()
        assert item["user_status"] == "active"

    async def test_measurement_count_is_scoped_to_this_establishment(self, body):
        # Juan took Bruno's two readings plus Clara's, all at establishment A.
        assert body["items"][0]["measurement_count"] == 3
        assert body["items"][0]["last_measured_at"].startswith("2024-06-11")

    async def test_pending_enrollments_are_filterable(
        self, client, admin_headers, scenario
    ):
        response = await client.get(
            FIELD_WORKERS_URL.format(establishment_id=scenario.establishment_a),
            headers=admin_headers,
            params={"relation_status": "pending"},
        )
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["last_name"] == "Pending"
        assert body["items"][0]["measurement_count"] == 0
        assert body["items"][0]["last_measured_at"] is None

    async def test_workers_of_other_establishments_are_excluded(self, body):
        assert "Diaz" not in {item["last_name"] for item in body["items"]}

    async def test_multiple_statuses_are_combined(
        self, client, admin_headers, scenario
    ):
        response = await client.get(
            FIELD_WORKERS_URL.format(establishment_id=scenario.establishment_a),
            headers=admin_headers,
            params={"relation_status": ["approved", "pending"]},
        )
        body = response.json()
        assert body["total"] == 2
        last_names = {item["last_name"] for item in body["items"]}
        assert last_names == {"Gomez", "Pending"}

    async def test_all_statuses_must_be_requested_explicitly(
        self, client, admin_headers, scenario
    ):
        response = await client.get(
            FIELD_WORKERS_URL.format(establishment_id=scenario.establishment_a),
            headers=admin_headers,
            params={"relation_status": ["approved", "pending", "rejected"]},
        )
        body = response.json()
        assert body["total"] == 3
        last_names = {item["last_name"] for item in body["items"]}
        assert last_names == {"Gomez", "Pending", "Rejected"}

    async def test_search_filters_by_email(self, client, admin_headers, scenario):
        response = await client.get(
            FIELD_WORKERS_URL.format(establishment_id=scenario.establishment_a),
            headers=admin_headers,
            params={"search": "Gomez"},
        )
        assert response.json()["total"] == 1
