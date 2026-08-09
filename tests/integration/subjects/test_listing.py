import uuid
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from fastapi import status

from app.domain.subject import SubjectSortOrder
from tests.integration.subjects.conftest import (
    SUBJECTS_URL,
    _make_establishment,
    _make_measurement,
    _make_subject,
    _upload,
)

pytestmark = pytest.mark.asyncio


class TestGetSubjectsPaginated:
    async def test_unauthenticated_returns_401(self, client):
        """No token on GET /subjects should return 401."""
        response = await client.get(SUBJECTS_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_empty_list_returns_200(self, client, field_worker_headers):
        """No subjects in the DB returns an empty list with zeroed metadata."""
        response = await client.get(SUBJECTS_URL, headers=field_worker_headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["total_pages"] == 0

    async def test_returns_subject_fields(self, client, field_worker_headers):
        """Response items carry the correct value for each plain subject field."""
        await _upload(client, field_worker_headers)
        response = await client.get(SUBJECTS_URL, headers=field_worker_headers)
        assert response.status_code == status.HTTP_200_OK
        item = response.json()["items"][0]
        assert "id" in item
        assert item["dni"] == 12345678
        assert item["name"] == "Juan"
        assert item["last_name"] == "Perez"
        assert item["sex"] == "male"
        assert item["birth_date"] == "2010-01-01"

    async def test_item_shape(self, client, field_worker_headers):
        """An item exposes exactly the listing fields -- no more, no less."""
        await _upload(client, field_worker_headers)
        response = await client.get(SUBJECTS_URL, headers=field_worker_headers)
        item = response.json()["items"][0]
        assert {
            "id",
            "dni",
            "name",
            "last_name",
            "sex",
            "birth_date",
            "latest_measurement",
        } == item.keys()

    async def test_never_measured_subject_has_null_latest_measurement(
        self, client, field_worker_headers
    ):
        """A subject with no measurements lists a null latest_measurement."""
        await _upload(client, field_worker_headers)
        response = await client.get(SUBJECTS_URL, headers=field_worker_headers)
        item = response.json()["items"][0]
        assert item["latest_measurement"] is None

    async def test_pagination_metadata(self, client, field_worker_headers):
        """With 5 subjects and page_size=2, total_pages should be 3."""
        for i in range(5):
            await _upload(client, field_worker_headers, dni=10000000 + i)
        response = await client.get(
            f"{SUBJECTS_URL}?page=1&page_size=2", headers=field_worker_headers
        )
        data = response.json()
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["page_size"] == 2
        assert data["total_pages"] == 3

    async def test_page_size_limits_results(self, client, field_worker_headers):
        """page_size controls how many items are returned."""
        for i in range(5):
            await _upload(client, field_worker_headers, dni=10000000 + i)
        response = await client.get(
            f"{SUBJECTS_URL}?page_size=3", headers=field_worker_headers
        )
        assert len(response.json()["items"]) == 3

    async def test_second_page_returns_different_items(
        self, client, field_worker_headers
    ):
        """Two consecutive pages share no subjects."""
        for i in range(4):
            await _upload(client, field_worker_headers, dni=10000000 + i)
        page1 = await client.get(
            f"{SUBJECTS_URL}?page=1&page_size=2", headers=field_worker_headers
        )
        page2 = await client.get(
            f"{SUBJECTS_URL}?page=2&page_size=2", headers=field_worker_headers
        )
        ids1 = {i["id"] for i in page1.json()["items"]}
        ids2 = {i["id"] for i in page2.json()["items"]}
        assert ids1.isdisjoint(ids2)

    async def test_offset_past_last_record_returns_empty(
        self, client, field_worker_headers
    ):
        """Requesting a page whose offset exceeds the total returns an empty list."""
        await _upload(client, field_worker_headers)
        response = await client.get(
            f"{SUBJECTS_URL}?page=99&page_size=20", headers=field_worker_headers
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["items"] == []

    async def test_invalid_page_returns_422(self, client, field_worker_headers):
        """page=0 is invalid, minimum is 1."""
        response = await client.get(
            f"{SUBJECTS_URL}?page=0", headers=field_worker_headers
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_invalid_page_size_zero_returns_422(
        self, client, field_worker_headers
    ):
        """page_size=0 is invalid, minimum is 1."""
        response = await client.get(
            f"{SUBJECTS_URL}?page_size=0", headers=field_worker_headers
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_invalid_page_size_above_max_returns_422(
        self, client, field_worker_headers
    ):
        """page_size=101 exceeds the maximum of 100."""
        response = await client.get(
            f"{SUBJECTS_URL}?page_size=101", headers=field_worker_headers
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_search_by_name_returns_matching(self, client, field_worker_headers):
        """Only subjects whose name contains the search term are returned."""
        await _upload(client, field_worker_headers, dni=11111111, name="Juan")
        await _upload(client, field_worker_headers, dni=22222222, name="Maria")
        response = await client.get(
            f"{SUBJECTS_URL}?search=Juan", headers=field_worker_headers
        )
        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Juan"

    async def test_search_by_last_name_returns_matching(
        self, client, field_worker_headers
    ):
        """Only subjects whose last name contains the search term are returned."""
        await _upload(client, field_worker_headers, dni=11111111, last_name="Perez")
        await _upload(client, field_worker_headers, dni=22222222, last_name="Garcia")
        response = await client.get(
            f"{SUBJECTS_URL}?search=Garcia", headers=field_worker_headers
        )
        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["last_name"] == "Garcia"

    async def test_search_by_dni_returns_matching(self, client, field_worker_headers):
        """A numeric search term matches against DNI exactly."""
        await _upload(client, field_worker_headers, dni=11111111)
        await _upload(client, field_worker_headers, dni=22222222)
        response = await client.get(
            f"{SUBJECTS_URL}?search=11111111", headers=field_worker_headers
        )
        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["dni"] == 11111111

    async def test_search_is_case_insensitive(self, client, field_worker_headers):
        """Search is case-insensitive: 'juan' matches 'Juan'."""
        await _upload(client, field_worker_headers, name="Juan")
        response = await client.get(
            f"{SUBJECTS_URL}?search=juan", headers=field_worker_headers
        )
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["items"]) == 1

    async def test_search_no_match_returns_empty(self, client, field_worker_headers):
        """A search term that matches nothing returns an empty list."""
        await _upload(client, field_worker_headers)
        response = await client.get(
            f"{SUBJECTS_URL}?search=zzznomatch", headers=field_worker_headers
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_search_whitespace_only_returns_all(
        self, client, field_worker_headers
    ):
        """A whitespace-only search is treated as no filter and returns all records."""
        await _upload(client, field_worker_headers, dni=11111111)
        await _upload(client, field_worker_headers, dni=22222222)
        response = await client.get(
            f"{SUBJECTS_URL}?search=   ", headers=field_worker_headers
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 2


class TestGetSubjectsPaginatedLatestMeasurement:
    """Each listing item carries the subject's own latest reading, across comedores."""

    @pytest_asyncio.fixture
    async def two_measured_subjects(self, app, field_worker_user_id):
        """Seed two subjects, each with their own measurement history.

        Subject A is measured twice, at two different establishments -- the
        older reading is at "Comedor Viejo", the newer one at "Comedor Nuevo".
        Subject B is measured once, at Comedor Viejo, and
        must not pick up A's measurement when both are resolved in the same
        batched listing query.
        """
        from app.db.database import AsyncSessionLocal
        from app.domain.subject import Sex

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
            subject_a = _make_subject(71234567, "Nico", "Medido", date(2018, 1, 1))
            subject_b = _make_subject(
                71234568, "Sol", "Medida", date(2019, 2, 2), sex=Sex.FEMALE
            )
            session.add_all([old_est, new_est, subject_a, subject_b])
            await session.flush()

            for weight, height, est, when in [
                (10.0, 120.0, old_est, datetime(2024, 1, 10, tzinfo=timezone.utc)),
                (20.0, 118.0, new_est, datetime(2024, 6, 10, tzinfo=timezone.utc)),
            ]:
                session.add(
                    _make_measurement(
                        subject_a.id,
                        field_worker_user_id,
                        est.id,
                        weight_kg=weight,
                        height_cm=height,
                        measured_at=when,
                    )
                )
            session.add(
                _make_measurement(
                    subject_b.id,
                    field_worker_user_id,
                    old_est.id,
                    weight_kg=15.0,
                    height_cm=100.0,
                    measured_at=datetime(2024, 3, 1, tzinfo=timezone.utc),
                )
            )
            await session.commit()
            return subject_a.id, subject_b.id

    @pytest_asyncio.fixture
    async def items_by_id(self, client, field_worker_headers, two_measured_subjects):
        response = await client.get(SUBJECTS_URL, headers=field_worker_headers)
        assert response.status_code == status.HTTP_200_OK
        return {item["id"]: item for item in response.json()["items"]}

    async def test_latest_measurement_wins_across_establishments(
        self, items_by_id, two_measured_subjects
    ):
        """A's listed reading is the global latest, not the Comedor Viejo one."""
        subject_a_id, _ = two_measured_subjects
        latest = items_by_id[str(subject_a_id)]["latest_measurement"]
        assert latest["measured_at"].startswith("2024-06-10")
        assert latest["establishment"]["name"] == "Comedor Nuevo"

    async def test_each_subject_gets_its_own_measurement(
        self, items_by_id, two_measured_subjects
    ):
        """The batched query doesn't cross-assign A's measurement to B,
        or vice versa."""
        subject_a_id, subject_b_id = two_measured_subjects
        latest_a = items_by_id[str(subject_a_id)]["latest_measurement"]
        latest_b = items_by_id[str(subject_b_id)]["latest_measurement"]
        assert latest_a["id"] != latest_b["id"]
        assert latest_b["weight_kg"] == 15.0
        assert latest_b["establishment"]["name"] == "Comedor Viejo"


class TestGetSubjectsPaginatedBirthDateFilter:
    """GET /subjects filters by birth_date_from/birth_date_to, both inclusive."""

    @pytest_asyncio.fixture
    async def three_subjects(self, client, field_worker_headers):
        """Seed three subjects with distinct, spread-out birthdays."""
        for dni, birth_date in [
            (81111111, "2015-01-01"),
            (81111112, "2018-06-15"),
            (81111113, "2020-12-31"),
        ]:
            response = await _upload(
                client, field_worker_headers, dni=dni, birth_date=birth_date
            )
            assert response.status_code == status.HTTP_201_CREATED

    async def test_filters_by_range(self, client, field_worker_headers, three_subjects):
        """Only the subject strictly inside the range is returned."""
        response = await client.get(
            f"{SUBJECTS_URL}?birth_date_from=2016-01-01&birth_date_to=2019-01-01",
            headers=field_worker_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert [item["birth_date"] for item in items] == ["2018-06-15"]

    async def test_range_boundaries_are_inclusive(
        self, client, field_worker_headers, three_subjects
    ):
        """Subjects born exactly on birth_date_from or birth_date_to are included."""
        response = await client.get(
            f"{SUBJECTS_URL}?birth_date_from=2015-01-01&birth_date_to=2020-12-31",
            headers=field_worker_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        birth_dates = {item["birth_date"] for item in response.json()["items"]}
        assert birth_dates == {"2015-01-01", "2018-06-15", "2020-12-31"}

    async def test_birth_date_from_alone_is_open_ended_above(
        self, client, field_worker_headers, three_subjects
    ):
        """With only birth_date_from set, subjects born on or after it all match."""
        response = await client.get(
            f"{SUBJECTS_URL}?birth_date_from=2018-01-01",
            headers=field_worker_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        birth_dates = {item["birth_date"] for item in response.json()["items"]}
        assert birth_dates == {"2018-06-15", "2020-12-31"}

    async def test_birth_date_to_alone_is_open_ended_below(
        self, client, field_worker_headers, three_subjects
    ):
        """With only birth_date_to set, subjects born on or before it all match."""
        response = await client.get(
            f"{SUBJECTS_URL}?birth_date_to=2018-01-01",
            headers=field_worker_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        birth_dates = {item["birth_date"] for item in response.json()["items"]}
        assert birth_dates == {"2015-01-01"}

    async def test_no_subject_in_range_returns_empty(
        self, client, field_worker_headers, three_subjects
    ):
        """A range that matches nobody returns an empty list, not an error."""
        response = await client.get(
            f"{SUBJECTS_URL}?birth_date_from=2021-01-01&birth_date_to=2022-01-01",
            headers=field_worker_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["items"] == []


class TestGetSubjectsPaginatedEstablishmentFilter:
    """GET /subjects filters by establishment_id: any measurement there counts."""

    @pytest_asyncio.fixture
    async def subjects_by_establishment(self, app, field_worker_user_id):
        """Seed two establishments and four subjects.

        X was measured only at Comedor A, Y only at Comedor B, Z at both (so it
        must match either filter), and W was never measured (so it must match
        neither). Returns a dict of establishment and subject ids.
        """
        from app.db.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            est_a = _make_establishment(
                "Comedor A",
                "Calle A",
                latitude=-34.9,
                longitude=-57.9,
                city="La Plata",
                province="Buenos Aires",
            )
            est_b = _make_establishment(
                "Comedor B",
                "Calle B",
                latitude=-31.4,
                longitude=-64.2,
                city="Cordoba",
                province="Cordoba",
            )
            subject_x, subject_y, subject_z, subject_w = (
                _make_subject(dni, name, "Subject", date(2015, 1, 1))
                for dni, name in [
                    (82111111, "X"),
                    (82111112, "Y"),
                    (82111113, "Z"),
                    (82111114, "W"),
                ]
            )
            session.add_all([est_a, est_b, subject_x, subject_y, subject_z, subject_w])
            await session.flush()

            for subject, est in [
                (subject_x, est_a),
                (subject_y, est_b),
                (subject_z, est_a),
                (subject_z, est_b),
            ]:
                session.add(
                    _make_measurement(
                        subject.id,
                        field_worker_user_id,
                        est.id,
                        weight_kg=15.0,
                        height_cm=100.0,
                        measured_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    )
                )
            await session.commit()
            return {
                "establishment_a": est_a.id,
                "establishment_b": est_b.id,
                "x": subject_x.id,
                "y": subject_y.id,
                "z": subject_z.id,
                "w": subject_w.id,
            }

    async def test_returns_subjects_measured_at_establishment(
        self, client, field_worker_headers, subjects_by_establishment
    ):
        """X (measured only there) and Z (measured there too) both match."""
        ids = subjects_by_establishment
        response = await client.get(
            SUBJECTS_URL,
            params={"establishment_id": str(ids["establishment_a"])},
            headers=field_worker_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        returned = {item["id"] for item in response.json()["items"]}
        assert returned == {str(ids["x"]), str(ids["z"])}

    async def test_matches_the_other_establishment_independently(
        self, client, field_worker_headers, subjects_by_establishment
    ):
        """Filtering by Comedor B returns Y and Z, not X -- the filter isn't global."""
        ids = subjects_by_establishment
        response = await client.get(
            SUBJECTS_URL,
            params={"establishment_id": str(ids["establishment_b"])},
            headers=field_worker_headers,
        )
        returned = {item["id"] for item in response.json()["items"]}
        assert returned == {str(ids["y"]), str(ids["z"])}

    async def test_never_measured_subject_is_never_included(
        self, client, field_worker_headers, subjects_by_establishment
    ):
        """W, who has no measurements anywhere, matches neither establishment."""
        ids = subjects_by_establishment
        for key in ("establishment_a", "establishment_b"):
            response = await client.get(
                SUBJECTS_URL,
                params={"establishment_id": str(ids[key])},
                headers=field_worker_headers,
            )
            returned = {item["id"] for item in response.json()["items"]}
            assert str(ids["w"]) not in returned

    async def test_unknown_establishment_id_returns_empty(
        self, client, field_worker_headers, subjects_by_establishment
    ):
        """An establishment id with no measurements returns an empty page, not 404."""
        response = await client.get(
            SUBJECTS_URL,
            params={"establishment_id": str(uuid.uuid4())},
            headers=field_worker_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["items"] == []


class TestGetSubjectsPaginatedAttributeFilters:
    """GET /subjects filters by is_rural, is_indigenous and sex, exact match."""

    @pytest_asyncio.fixture
    async def four_subjects(self, client, field_worker_headers):
        """Seed subjects covering every combination of rurality and indigenous
        status, plus both sexes."""
        combos = [
            (83111111, "male", True, True),
            (83111112, "female", True, False),
            (83111113, "female", False, True),
            (83111114, "male", False, False),
        ]
        for dni, sex, is_rural, is_indigenous in combos:
            response = await _upload(
                client,
                field_worker_headers,
                dni=dni,
                sex=sex,
                is_rural=is_rural,
                is_indigenous=is_indigenous,
            )
            assert response.status_code == status.HTTP_201_CREATED

    async def test_filters_by_is_rural(
        self, client, field_worker_headers, four_subjects
    ):
        """Only the two rural subjects are returned, regardless of the other fields."""
        response = await client.get(
            SUBJECTS_URL, params={"is_rural": True}, headers=field_worker_headers
        )
        dnis = {item["dni"] for item in response.json()["items"]}
        assert dnis == {83111111, 83111112}

    async def test_filters_by_is_indigenous(
        self, client, field_worker_headers, four_subjects
    ):
        """Only the two indigenous subjects are returned."""
        response = await client.get(
            SUBJECTS_URL, params={"is_indigenous": True}, headers=field_worker_headers
        )
        dnis = {item["dni"] for item in response.json()["items"]}
        assert dnis == {83111111, 83111113}

    async def test_filters_by_sex(self, client, field_worker_headers, four_subjects):
        """Only the two female subjects are returned."""
        response = await client.get(
            SUBJECTS_URL, params={"sex": "female"}, headers=field_worker_headers
        )
        dnis = {item["dni"] for item in response.json()["items"]}
        assert dnis == {83111112, 83111113}

    async def test_combines_filters_with_and(
        self, client, field_worker_headers, four_subjects
    ):
        """is_rural and sex combine with AND, not OR."""
        response = await client.get(
            SUBJECTS_URL,
            params={"is_rural": True, "sex": "female"},
            headers=field_worker_headers,
        )
        dnis = {item["dni"] for item in response.json()["items"]}
        assert dnis == {83111112}


class TestGetSubjectsPaginatedSortOrder:
    """GET /subjects sorts by name, created_at or birth_date, in either direction."""

    @pytest_asyncio.fixture
    async def three_ordered_subjects(self, client, field_worker_headers):
        """Seed three subjects whose creation order, names and birth dates each
        yield a different, unambiguous permutation.

        Creation order: Carlos, Ana, Beatriz.
        Name order (asc): Ana, Beatriz, Carlos.
        Birthdate order (asc, oldest first): Ana (1990), Carlos (2000), Beatriz (2010).
        """
        for dni, name, birth_date in [
            (84111111, "Carlos", "2000-01-01"),
            (84111112, "Ana", "1990-01-01"),
            (84111113, "Beatriz", "2010-01-01"),
        ]:
            response = await _upload(
                client, field_worker_headers, dni=dni, name=name, birth_date=birth_date
            )
            assert response.status_code == status.HTTP_201_CREATED

    async def _names(self, client, field_worker_headers, sort_order):
        response = await client.get(
            SUBJECTS_URL,
            params={"sort_order": sort_order},
            headers=field_worker_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        return [item["name"] for item in response.json()["items"]]

    async def test_default_sort_is_newest_created_first(
        self, client, field_worker_headers, three_ordered_subjects
    ):
        """With no sort_order, subjects come back newest-created-first, as before."""
        response = await client.get(SUBJECTS_URL, headers=field_worker_headers)
        names = [item["name"] for item in response.json()["items"]]
        assert names == ["Beatriz", "Ana", "Carlos"]

    async def test_created_at_desc_explicit(
        self, client, field_worker_headers, three_ordered_subjects
    ):
        """The default behavior is also reachable as an explicit query value."""
        names = await self._names(
            client, field_worker_headers, SubjectSortOrder.CREATED_AT_DESC
        )
        assert names == ["Beatriz", "Ana", "Carlos"]

    async def test_created_at_asc(
        self, client, field_worker_headers, three_ordered_subjects
    ):
        """Oldest-created-first is the reverse of the default order."""
        names = await self._names(
            client, field_worker_headers, SubjectSortOrder.CREATED_AT_ASC
        )
        assert names == ["Carlos", "Ana", "Beatriz"]

    async def test_name_asc(self, client, field_worker_headers, three_ordered_subjects):
        """Alphabetical order by name, independent of creation order."""
        names = await self._names(
            client, field_worker_headers, SubjectSortOrder.NAME_ASC
        )
        assert names == ["Ana", "Beatriz", "Carlos"]

    async def test_name_desc(
        self, client, field_worker_headers, three_ordered_subjects
    ):
        """Reverse-alphabetical order by name."""
        names = await self._names(
            client, field_worker_headers, SubjectSortOrder.NAME_DESC
        )
        assert names == ["Carlos", "Beatriz", "Ana"]

    async def test_birth_date_asc(
        self, client, field_worker_headers, three_ordered_subjects
    ):
        """Oldest-born-first -- this is also how a frontend would sort by age desc."""
        names = await self._names(
            client, field_worker_headers, SubjectSortOrder.BIRTH_DATE_ASC
        )
        assert names == ["Ana", "Carlos", "Beatriz"]

    async def test_birth_date_desc(
        self, client, field_worker_headers, three_ordered_subjects
    ):
        """Youngest-born-first -- this is also how a frontend would sort by age asc."""
        names = await self._names(
            client, field_worker_headers, SubjectSortOrder.BIRTH_DATE_DESC
        )
        assert names == ["Beatriz", "Carlos", "Ana"]


class TestGetSubjectsPaginatedValidation:
    """GET /subjects rejects an inverted birth_date range with 400."""

    async def test_birth_date_from_after_birth_date_to_returns_400(
        self, client, field_worker_headers
    ):
        """An inverted range is rejected with the same detail InvalidListingFilterError
        produces for other listings (e.g. MeasurementListingQuery)."""
        response = await client.get(
            SUBJECTS_URL,
            params={"birth_date_from": "2020-01-01", "birth_date_to": "2019-01-01"},
            headers=field_worker_headers,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            response.json()["detail"] == "birth_date_from cannot be after birth_date_to"
        )

    async def test_equal_from_and_to_is_a_valid_single_day_range(
        self, client, field_worker_headers
    ):
        """from == to is a one-day range, not an inverted one."""
        await _upload(
            client, field_worker_headers, dni=85111111, birth_date="2020-01-01"
        )
        response = await client.get(
            SUBJECTS_URL,
            params={"birth_date_from": "2020-01-01", "birth_date_to": "2020-01-01"},
            headers=field_worker_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 1
