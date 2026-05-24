import uuid
from datetime import date, timedelta

import pytest
from fastapi import status
from jose import jwt

from app.core.security import create_access_token
from app.domain.user import UserRole

pytestmark = pytest.mark.asyncio

SUBJECTS_URL = "/api/v1/subjects"


@pytest.fixture
def manager_headers():
    token = create_access_token(uuid.uuid4(), role=UserRole.ESTABLISHMENT_MANAGER)
    return {"Authorization": f"Bearer {token}"}


def _body(**overrides):
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
        SUBJECTS_URL, json=_body(**overrides), headers=headers or {}
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
                "role": "establishment_manager",
                "type": "access",
            },
            "wrong_secret",
            algorithm="HS256",
        )
        response = await _upload(client, headers={"Authorization": f"Bearer {forged}"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_admin_role_returns_403(self, client):
        """A valid token with admin role should return 403."""
        token = create_access_token(uuid.uuid4(), role=UserRole.ADMIN)
        response = await _upload(client, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_professional_role_returns_403(self, client):
        """A valid token with professional role should return 403."""
        token = create_access_token(uuid.uuid4(), role=UserRole.PROFESSIONAL)
        response = await _upload(client, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_valid_request_returns_201(self, client, manager_headers):
        """A well-formed request with a manager token returns 201."""
        response = await _upload(client, manager_headers)
        assert response.status_code == status.HTTP_201_CREATED

    async def test_valid_request_returns_subject_data(self, client, manager_headers):
        """Response body includes all submitted fields and a generated id."""
        response = await _upload(client, manager_headers)
        data = response.json()
        assert "id" in data
        assert data["dni"] == 12345678
        assert data["sex"] == "male"
        assert data["name"] == "Juan"
        assert data["last_name"] == "Perez"
        assert data["birth_date"] == "2010-01-01"
        assert data["is_rural"] is False
        assert data["is_indigenous"] is False

    async def test_duplicate_dni_returns_409(self, client, manager_headers):
        """Registering a second subject with the same DNI returns 409."""
        await _upload(client, manager_headers)
        response = await _upload(client, manager_headers)
        assert response.status_code == status.HTTP_409_CONFLICT

    async def test_future_birth_date_returns_422(self, client, manager_headers):
        """A birth date in the future is rejected with 422."""
        future = (date.today() + timedelta(days=1)).isoformat()
        response = await _upload(client, manager_headers, birth_date=future)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_dni_zero_returns_422(self, client, manager_headers):
        """DNI 0 is below the minimum allowed value."""
        response = await _upload(client, manager_headers, dni=0)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_dni_above_max_returns_422(self, client, manager_headers):
        """DNI above 99999999 exceeds the Argentine DNI range."""
        response = await _upload(client, manager_headers, dni=100000000)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_whitespace_name_returns_422(self, client, manager_headers):
        """A name composed only of whitespace is rejected after stripping."""
        response = await _upload(client, manager_headers, name="   ")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.parametrize(
        "field",
        ["dni", "sex", "name", "last_name", "birth_date", "is_rural", "is_indigenous"],
    )
    async def test_each_required_field_is_mandatory(
        self, client, manager_headers, field
    ):
        """Omitting any single required field returns 422."""
        body = _body()
        del body[field]
        response = await client.post(SUBJECTS_URL, json=body, headers=manager_headers)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


class TestGetSubject:
    async def test_returns_200_with_subject_data(self, client, manager_headers):
        """A subject that was just created can be retrieved by id."""
        created = (await _upload(client, manager_headers)).json()
        response = await client.get(
            f"{SUBJECTS_URL}/{created['id']}", headers=manager_headers
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == created

    async def test_unknown_id_returns_404(self, client, manager_headers):
        """A random UUID that was never registered returns 404."""
        response = await client.get(
            f"{SUBJECTS_URL}/{uuid.uuid4()}", headers=manager_headers
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_unauthenticated_returns_401(self, client):
        """No token on GET should return 401."""
        response = await client.get(f"{SUBJECTS_URL}/{uuid.uuid4()}")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_non_manager_role_returns_403(self, client):
        """A valid token with a non-manager role on GET should return 403."""
        token = create_access_token(uuid.uuid4(), role=UserRole.PROFESSIONAL)
        response = await client.get(
            f"{SUBJECTS_URL}/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestGetSubjectsPaginated:
    async def test_unauthenticated_returns_401(self, client):
        """No token on GET /subjects should return 401."""
        response = await client.get(SUBJECTS_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_empty_list_returns_200(self, client, manager_headers):
        """No subjects in the DB returns an empty list with zeroed metadata."""
        response = await client.get(SUBJECTS_URL, headers=manager_headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["total_pages"] == 0

    async def test_returns_subject_fields(self, client, manager_headers):
        """Response items include id, dni, name, last_name and sex."""
        await _upload(client, manager_headers)
        response = await client.get(SUBJECTS_URL, headers=manager_headers)
        assert response.status_code == status.HTTP_200_OK
        item = response.json()["items"][0]
        assert "id" in item
        assert item["dni"] == 12345678
        assert item["name"] == "Juan"
        assert item["last_name"] == "Perez"
        assert item["sex"] == "male"

    async def test_pagination_metadata(self, client, manager_headers):
        """With 5 subjects and page_size=2, total_pages should be 3."""
        for i in range(5):
            await _upload(client, manager_headers, dni=10000000 + i)
        response = await client.get(
            f"{SUBJECTS_URL}?page=1&page_size=2", headers=manager_headers
        )
        data = response.json()
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["page_size"] == 2
        assert data["total_pages"] == 3

    async def test_page_size_limits_results(self, client, manager_headers):
        """page_size controls how many items are returned."""
        for i in range(5):
            await _upload(client, manager_headers, dni=10000000 + i)
        response = await client.get(
            f"{SUBJECTS_URL}?page_size=3", headers=manager_headers
        )
        assert len(response.json()["items"]) == 3

    async def test_second_page_returns_different_items(self, client, manager_headers):
        """Two consecutive pages share no subjects."""
        for i in range(4):
            await _upload(client, manager_headers, dni=10000000 + i)
        page1 = await client.get(
            f"{SUBJECTS_URL}?page=1&page_size=2", headers=manager_headers
        )
        page2 = await client.get(
            f"{SUBJECTS_URL}?page=2&page_size=2", headers=manager_headers
        )
        ids1 = {i["id"] for i in page1.json()["items"]}
        ids2 = {i["id"] for i in page2.json()["items"]}
        assert ids1.isdisjoint(ids2)

    async def test_offset_past_last_record_returns_empty(self, client, manager_headers):
        """Requesting a page whose offset exceeds the total returns an empty list."""
        await _upload(client, manager_headers)
        response = await client.get(
            f"{SUBJECTS_URL}?page=99&page_size=20", headers=manager_headers
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["items"] == []

    async def test_invalid_page_returns_422(self, client, manager_headers):
        """page=0 is invalid, minimum is 1."""
        response = await client.get(f"{SUBJECTS_URL}?page=0", headers=manager_headers)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_invalid_page_size_zero_returns_422(self, client, manager_headers):
        """page_size=0 is invalid, minimum is 1."""
        response = await client.get(
            f"{SUBJECTS_URL}?page_size=0", headers=manager_headers
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_invalid_page_size_above_max_returns_422(
        self, client, manager_headers
    ):
        """page_size=101 exceeds the maximum of 100."""
        response = await client.get(
            f"{SUBJECTS_URL}?page_size=101", headers=manager_headers
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_search_by_name_returns_matching(self, client, manager_headers):
        """Only subjects whose name contains the search term are returned."""
        await _upload(client, manager_headers, dni=11111111, name="Juan")
        await _upload(client, manager_headers, dni=22222222, name="Maria")
        response = await client.get(
            f"{SUBJECTS_URL}?search=Juan", headers=manager_headers
        )
        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Juan"

    async def test_search_by_last_name_returns_matching(self, client, manager_headers):
        """Only subjects whose last name contains the search term are returned."""
        await _upload(client, manager_headers, dni=11111111, last_name="Perez")
        await _upload(client, manager_headers, dni=22222222, last_name="Garcia")
        response = await client.get(
            f"{SUBJECTS_URL}?search=Garcia", headers=manager_headers
        )
        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["last_name"] == "Garcia"

    async def test_search_by_dni_returns_matching(self, client, manager_headers):
        """A numeric search term matches against DNI exactly."""
        await _upload(client, manager_headers, dni=11111111)
        await _upload(client, manager_headers, dni=22222222)
        response = await client.get(
            f"{SUBJECTS_URL}?search=11111111", headers=manager_headers
        )
        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["dni"] == 11111111

    async def test_search_is_case_insensitive(self, client, manager_headers):
        """Search is case-insensitive: 'juan' matches 'Juan'."""
        await _upload(client, manager_headers, name="Juan")
        response = await client.get(
            f"{SUBJECTS_URL}?search=juan", headers=manager_headers
        )
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["items"]) == 1

    async def test_search_no_match_returns_empty(self, client, manager_headers):
        """A search term that matches nothing returns an empty list."""
        await _upload(client, manager_headers)
        response = await client.get(
            f"{SUBJECTS_URL}?search=zzznomatch", headers=manager_headers
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_search_whitespace_only_returns_all(self, client, manager_headers):
        """A whitespace-only search is treated as no filter and returns all records."""
        await _upload(client, manager_headers, dni=11111111)
        await _upload(client, manager_headers, dni=22222222)
        response = await client.get(
            f"{SUBJECTS_URL}?search=   ", headers=manager_headers
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 2
