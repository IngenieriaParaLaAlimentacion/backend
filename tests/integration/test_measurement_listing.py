import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

import pytest_asyncio
from fastapi import status

LISTING_URL = "/api/v1/measurements"
EVOLUTION_URL = "/api/v1/subjects/{subject_id}/measurements/evolution"


def _bmi(weight_kg: float, height_cm: float) -> float:
    return weight_kg / (height_cm / 100) ** 2


def _birth_date_for_age(age: int) -> date:
    """A birth date that yields exactly ``age`` years old today (any day but Jan 1)."""
    return date(date.today().year - age, 1, 1)


@dataclass
class Scenario:
    establishment_a: uuid.UUID  # La Plata / Buenos Aires
    establishment_b: uuid.UUID  # Cordoba / Cordoba
    responsible_1: uuid.UUID  # Juan Gomez
    responsible_2: uuid.UUID  # Ana Diaz
    subject_old: uuid.UUID  # age 6, two measurements at establishment A by R1
    subject_young: uuid.UUID  # age 3, one measurement at establishment B by R2
    subject_no_data: uuid.UUID  # no measurements
    m_old_early: uuid.UUID  # 2024-01-01
    m_old_late: uuid.UUID  # 2024-06-01
    m_young: uuid.UUID  # 2025-03-01


@pytest_asyncio.fixture
async def scenario(app) -> Scenario:
    """Seed establishments, users, subjects and measurements for listing tests."""
    from app.db.database import AsyncSessionLocal
    from app.domain.subject import Sex
    from app.domain.user import UserStatus
    from app.models.auth.user import User
    from app.models.auth.user import UserRole as ORMUserRole
    from app.models.establishments.establishment import Establishment
    from app.models.measurements.measurement import Measurement
    from app.models.subjects.subject import Subject

    data = {}
    async with AsyncSessionLocal() as session:
        est_a = Establishment(
            name="Centro La Plata",
            formatted_address="Calle 1",
            latitude=-34.9,
            longitude=-57.9,
            place_id=f"place-{uuid.uuid4().hex[:8]}",
            city="La Plata",
            province="Buenos Aires",
        )
        est_b = Establishment(
            name="Centro Cordoba",
            formatted_address="Calle 2",
            latitude=-31.4,
            longitude=-64.2,
            place_id=f"place-{uuid.uuid4().hex[:8]}",
            city="Cordoba",
            province="Cordoba",
        )
        r1 = User(
            name="Juan",
            last_name="Gomez",
            email=f"{uuid.uuid4()}@test.com",
            role=ORMUserRole.FIELD_WORKER,
            status=UserStatus.ACTIVE,
        )
        r2 = User(
            name="Ana",
            last_name="Diaz",
            email=f"{uuid.uuid4()}@test.com",
            role=ORMUserRole.FIELD_WORKER,
            status=UserStatus.ACTIVE,
        )
        s_old = Subject(
            dni=10000001,
            sex=Sex.MALE,
            name="Nico",
            last_name="Old",
            birth_date=_birth_date_for_age(6),
            is_rural=False,
            is_indigenous=False,
        )
        s_young = Subject(
            dni=10000002,
            sex=Sex.FEMALE,
            name="Mia",
            last_name="Young",
            birth_date=_birth_date_for_age(3),
            is_rural=False,
            is_indigenous=False,
        )
        s_none = Subject(
            dni=10000003,
            sex=Sex.MALE,
            name="Sin",
            last_name="Data",
            birth_date=_birth_date_for_age(5),
            is_rural=False,
            is_indigenous=False,
        )
        session.add_all([est_a, est_b, r1, r2, s_old, s_young, s_none])
        await session.flush()

        m_old_early = Measurement(
            subject_id=s_old.id,
            responsible_id=r1.id,
            establishment_id=est_a.id,
            weight_kg=20.0,
            height_cm=110.0,
            bmi=_bmi(20.0, 110.0),
            measured_at=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
        )
        m_old_late = Measurement(
            subject_id=s_old.id,
            responsible_id=r1.id,
            establishment_id=est_a.id,
            weight_kg=22.0,
            height_cm=112.0,
            bmi=_bmi(22.0, 112.0),
            measured_at=datetime(2024, 6, 1, 10, 0, tzinfo=timezone.utc),
        )
        m_young = Measurement(
            subject_id=s_young.id,
            responsible_id=r2.id,
            establishment_id=est_b.id,
            weight_kg=14.0,
            height_cm=95.0,
            bmi=_bmi(14.0, 95.0),
            measured_at=datetime(2025, 3, 1, 10, 0, tzinfo=timezone.utc),
        )
        session.add_all([m_old_early, m_old_late, m_young])
        await session.commit()

        data = Scenario(
            establishment_a=est_a.id,
            establishment_b=est_b.id,
            responsible_1=r1.id,
            responsible_2=r2.id,
            subject_old=s_old.id,
            subject_young=s_young.id,
            subject_no_data=s_none.id,
            m_old_early=m_old_early.id,
            m_old_late=m_old_late.id,
            m_young=m_young.id,
        )
    return data


# --------------------------------------------------------------------------- #
# Listing — GET /api/v1/measurements
# --------------------------------------------------------------------------- #


class TestListingAuth:
    async def test_unauthenticated_returns_401(self, client):
        response = await client.get(LISTING_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_field_worker_is_forbidden(self, client, field_worker_headers):
        response = await client.get(LISTING_URL, headers=field_worker_headers)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_admin_is_allowed(self, client, admin_headers):
        response = await client.get(LISTING_URL, headers=admin_headers)
        assert response.status_code == status.HTTP_200_OK

    async def test_analyst_is_allowed(self, client, analyst_headers):
        response = await client.get(LISTING_URL, headers=analyst_headers)
        assert response.status_code == status.HTTP_200_OK


class TestListingShape:
    async def test_returns_enriched_paginated_shape(
        self, client, admin_headers, scenario
    ):
        response = await client.get(LISTING_URL, headers=admin_headers)
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == 3
        assert {"items", "total", "page", "page_size", "total_pages"} <= body.keys()

        item = body["items"][0]
        assert {
            "id",
            "measured_at",
            "weight_kg",
            "height_cm",
            "bmi",
            "subject",
            "establishment",
            "responsible",
            "alerts",
        } <= item.keys()
        assert {"id", "dni", "sex", "name", "last_name", "birth_date"} <= item[
            "subject"
        ].keys()
        assert {"id", "name", "city", "province"} <= item["establishment"].keys()
        assert {"id", "name", "last_name"} <= item["responsible"].keys()


class TestListingBmiRounding:
    async def test_bmi_is_rounded_to_two_decimals(
        self, client, admin_headers, scenario
    ):
        response = await client.get(
            LISTING_URL,
            params={"subject_id": str(scenario.subject_young)},
            headers=admin_headers,
        )
        bmi = response.json()["items"][0]["bmi"]
        # raw 14 / (0.95**2) = 15.5124... -> 15.51
        assert bmi == round(_bmi(14.0, 95.0), 2)
        assert bmi == 15.51


class TestListingFilters:
    async def test_filter_by_subject(self, client, admin_headers, scenario):
        response = await client.get(
            LISTING_URL,
            params={"subject_id": str(scenario.subject_old)},
            headers=admin_headers,
        )
        body = response.json()
        assert body["total"] == 2
        assert all(
            i["subject"]["id"] == str(scenario.subject_old) for i in body["items"]
        )

    async def test_filter_by_establishment(self, client, admin_headers, scenario):
        response = await client.get(
            LISTING_URL,
            params={"establishment_id": str(scenario.establishment_b)},
            headers=admin_headers,
        )
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == str(scenario.m_young)

    async def test_filter_by_city_is_case_insensitive(
        self, client, admin_headers, scenario
    ):
        response = await client.get(
            LISTING_URL, params={"city": "la plata"}, headers=admin_headers
        )
        body = response.json()
        assert body["total"] == 2
        assert all(i["establishment"]["city"] == "La Plata" for i in body["items"])

    async def test_filter_by_province(self, client, admin_headers, scenario):
        response = await client.get(
            LISTING_URL, params={"province": "Cordoba"}, headers=admin_headers
        )
        body = response.json()
        assert body["total"] == 1

    async def test_filter_by_responsible(self, client, admin_headers, scenario):
        response = await client.get(
            LISTING_URL,
            params={"responsible_id": str(scenario.responsible_1)},
            headers=admin_headers,
        )
        body = response.json()
        assert body["total"] == 2
        assert all(
            i["responsible"]["id"] == str(scenario.responsible_1) for i in body["items"]
        )

    async def test_filter_by_date_range(self, client, admin_headers, scenario):
        response = await client.get(
            LISTING_URL,
            params={
                "measured_from": "2024-03-01T00:00:00Z",
                "measured_to": "2024-12-31T23:59:59Z",
            },
            headers=admin_headers,
        )
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == str(scenario.m_old_late)

    async def test_filter_by_min_age(self, client, admin_headers, scenario):
        """min_age=5 keeps only the 6yo subject's measurements."""
        response = await client.get(
            LISTING_URL, params={"min_age": 5}, headers=admin_headers
        )
        body = response.json()
        assert body["total"] == 2
        assert all(
            i["subject"]["id"] == str(scenario.subject_old) for i in body["items"]
        )

    async def test_filter_by_max_age(self, client, admin_headers, scenario):
        """max_age=4 keeps only the 3yo subject's measurement."""
        response = await client.get(
            LISTING_URL, params={"max_age": 4}, headers=admin_headers
        )
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["subject"]["id"] == str(scenario.subject_young)


class TestListingSort:
    async def test_sort_date_asc(self, client, admin_headers, scenario):
        response = await client.get(
            LISTING_URL,
            params={"subject_id": str(scenario.subject_old), "sort_order": "date_asc"},
            headers=admin_headers,
        )
        ids = [i["id"] for i in response.json()["items"]]
        assert ids == [str(scenario.m_old_early), str(scenario.m_old_late)]

    async def test_sort_date_desc_is_default(self, client, admin_headers, scenario):
        response = await client.get(
            LISTING_URL,
            params={"subject_id": str(scenario.subject_old)},
            headers=admin_headers,
        )
        ids = [i["id"] for i in response.json()["items"]]
        assert ids == [str(scenario.m_old_late), str(scenario.m_old_early)]


class TestListingValidation:
    async def test_min_age_greater_than_max_age_returns_400(
        self, client, admin_headers
    ):
        response = await client.get(
            LISTING_URL,
            params={"min_age": 10, "max_age": 5},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_measured_from_after_measured_to_returns_400(
        self, client, admin_headers
    ):
        response = await client.get(
            LISTING_URL,
            params={
                "measured_from": "2025-01-01T00:00:00Z",
                "measured_to": "2024-01-01T00:00:00Z",
            },
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestListingPagination:
    async def test_page_size_limits_items_and_reports_total_pages(
        self, client, admin_headers, scenario
    ):
        response = await client.get(
            LISTING_URL, params={"page_size": 2}, headers=admin_headers
        )
        body = response.json()
        assert body["total"] == 3
        assert body["page_size"] == 2
        assert body["total_pages"] == 2
        assert len(body["items"]) == 2


# --------------------------------------------------------------------------- #
# Evolution — GET /api/v1/subjects/{subject_id}/measurements/evolution
# --------------------------------------------------------------------------- #


class TestEvolutionAuth:
    async def test_unauthenticated_returns_401(self, client, scenario):
        response = await client.get(
            EVOLUTION_URL.format(subject_id=scenario.subject_old)
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_field_worker_is_forbidden(
        self, client, field_worker_headers, scenario
    ):
        response = await client.get(
            EVOLUTION_URL.format(subject_id=scenario.subject_old),
            headers=field_worker_headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestEvolutionNotFound:
    async def test_unknown_subject_returns_404(self, client, admin_headers):
        response = await client.get(
            EVOLUTION_URL.format(subject_id=uuid.uuid4()), headers=admin_headers
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestEvolutionResults:
    async def test_returns_subject_and_points_oldest_first_by_default(
        self, client, admin_headers, scenario
    ):
        response = await client.get(
            EVOLUTION_URL.format(subject_id=scenario.subject_old),
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["subject"]["id"] == str(scenario.subject_old)
        dates = [p["measured_at"] for p in body["points"]]
        assert dates == sorted(dates)
        assert len(body["points"]) == 2
        point = body["points"][0]
        assert {"measured_at", "weight_kg", "height_cm", "bmi", "alerts"} <= (
            point.keys()
        )

    async def test_newest_first_order(self, client, admin_headers, scenario):
        response = await client.get(
            EVOLUTION_URL.format(subject_id=scenario.subject_old),
            params={"order": "newest_first"},
            headers=admin_headers,
        )
        dates = [p["measured_at"] for p in response.json()["points"]]
        assert dates == sorted(dates, reverse=True)

    async def test_subject_without_measurements_returns_empty_points(
        self, client, admin_headers, scenario
    ):
        response = await client.get(
            EVOLUTION_URL.format(subject_id=scenario.subject_no_data),
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["points"] == []
