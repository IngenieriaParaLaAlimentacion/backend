import uuid

import pytest
from fastapi import status
from sqlalchemy import select

import app.db.database as db_module
from app.domain.user import UserRole, UserStatus
from app.models.auth.user import User
from app.models.auth.user_establishment import UserEstablishment
from tests.integration.admin.conftest import (
    ADMIN_USERS_URL,
    APPROVE_FIELD_WORKER_URL,
    APPROVE_URL,
    REGISTER_FIELD_WORKER_URL,
    REJECT_FIELD_WORKER_URL,
    REJECT_URL,
    _insert_user,
)

pytestmark = pytest.mark.asyncio


class TestApproveEstablishments:
    async def test_returns_no_content(
        self, client, admin_headers, accepted_field_worker, db_establishment
    ):
        """Should return 204 on successful approval."""
        url = APPROVE_URL.format(user_id=accepted_field_worker["id"])
        response = await client.patch(
            url,
            json={"establishment_ids": [str(db_establishment.id)]},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

    async def test_pending_account_returns_400(
        self, client, admin_headers, registered_field_worker, db_establishment
    ):
        """Establishment access requires an already-accepted account."""
        url = APPROVE_URL.format(user_id=registered_field_worker["id"])
        response = await client.patch(
            url,
            json={"establishment_ids": [str(db_establishment.id)]},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_idempotent_when_called_twice(
        self, client, admin_headers, accepted_field_worker, db_establishment
    ):
        """Calling approve twice should return 204 both times."""
        url = APPROVE_URL.format(user_id=accepted_field_worker["id"])
        body = {"establishment_ids": [str(db_establishment.id)]}

        first = await client.patch(url, json=body, headers=admin_headers)
        second = await client.patch(url, json=body, headers=admin_headers)

        assert first.status_code == status.HTTP_204_NO_CONTENT
        assert second.status_code == status.HTTP_204_NO_CONTENT

    async def test_user_not_found(self, client, admin_headers):
        """Should return 404 if the field worker does not exist."""
        url = APPROVE_URL.format(user_id=uuid.uuid4())
        response = await client.patch(
            url,
            json={"establishment_ids": [str(uuid.uuid4())]},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_establishment_not_associated_with_field_worker(
        self, client, admin_headers, accepted_field_worker
    ):
        """Should return 404 if an establishment ID is not linked to
        this field worker."""
        url = APPROVE_URL.format(user_id=accepted_field_worker["id"])
        response = await client.patch(
            url,
            json={"establishment_ids": [str(uuid.uuid4())]},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_empty_ids_rejected(
        self, client, admin_headers, registered_field_worker
    ):
        """Should return 422 if establishment_ids is empty."""
        url = APPROVE_URL.format(user_id=registered_field_worker["id"])
        response = await client.patch(
            url,
            json={"establishment_ids": []},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_user_is_not_a_field_worker(
        self, client, admin_headers, non_field_worker_user_id
    ):
        """Should return 404 when the target user has no matching
        establishment relations."""
        url = APPROVE_URL.format(user_id=non_field_worker_user_id)
        response = await client.patch(
            url,
            json={"establishment_ids": [str(uuid.uuid4())]},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestRejectEstablishments:
    async def test_returns_no_content(
        self, client, admin_headers, registered_field_worker, db_establishment
    ):
        """Should return 204 on successful rejection."""
        url = REJECT_URL.format(user_id=registered_field_worker["id"])
        response = await client.patch(
            url,
            json={"establishment_ids": [str(db_establishment.id)]},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

    async def test_rejected_establishment_has_rejected_status(
        self, client, admin_headers, registered_field_worker, db_establishment
    ):
        """The user-establishment relation should be REJECTED in the database."""
        url = REJECT_URL.format(user_id=registered_field_worker["id"])
        await client.patch(
            url,
            json={"establishment_ids": [str(db_establishment.id)]},
            headers=admin_headers,
        )

        async with db_module.AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserEstablishment).where(
                    UserEstablishment.establishment_id == db_establishment.id
                )
            )
            relation = result.scalar_one()
        assert relation.status.value == "rejected"

    async def test_user_status_unchanged_after_reject(
        self, client, admin_headers, registered_field_worker, db_establishment
    ):
        """Rejecting establishments must not activate the field worker."""
        url = REJECT_URL.format(user_id=registered_field_worker["id"])
        await client.patch(
            url,
            json={"establishment_ids": [str(db_establishment.id)]},
            headers=admin_headers,
        )

        list_response = await client.get(ADMIN_USERS_URL, headers=admin_headers)
        users = list_response.json()["items"]
        field_worker = next(
            u for u in users if u["id"] == registered_field_worker["id"]
        )
        assert field_worker["status"] == UserStatus.PENDING_VALIDATION

    async def test_user_not_found(self, client, admin_headers):
        """Should return 404 if the field worker does not exist."""
        url = REJECT_URL.format(user_id=uuid.uuid4())
        response = await client.patch(
            url,
            json={"establishment_ids": [str(uuid.uuid4())]},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_establishment_not_associated_with_field_worker(
        self, client, admin_headers, registered_field_worker
    ):
        """Should return 404 if an establishment ID is not linked to
        this field worker."""
        url = REJECT_URL.format(user_id=registered_field_worker["id"])
        response = await client.patch(
            url,
            json={"establishment_ids": [str(uuid.uuid4())]},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_empty_ids_rejected(
        self, client, admin_headers, registered_field_worker
    ):
        """Should return 422 if establishment_ids is empty."""
        url = REJECT_URL.format(user_id=registered_field_worker["id"])
        response = await client.patch(
            url,
            json={"establishment_ids": []},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_user_is_not_a_field_worker(
        self, client, admin_headers, non_field_worker_user_id
    ):
        """Should return 404 when the target user has no
        matching establishment relations."""
        url = REJECT_URL.format(user_id=non_field_worker_user_id)
        response = await client.patch(
            url,
            json={"establishment_ids": [str(uuid.uuid4())]},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestApproveFieldWorker:
    async def test_returns_no_content(
        self, client, admin_headers, registered_field_worker
    ):
        """Should return 204 without a body."""
        url = APPROVE_FIELD_WORKER_URL.format(user_id=registered_field_worker["id"])
        response = await client.patch(
            url, json={"establishment_ids": []}, headers=admin_headers
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

    async def test_field_worker_status_becomes_active(
        self, client, admin_headers, registered_field_worker
    ):
        """The account should be usable after approval."""
        url = APPROVE_FIELD_WORKER_URL.format(user_id=registered_field_worker["id"])
        response = await client.patch(
            url, json={"establishment_ids": []}, headers=admin_headers
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

        async with db_module.AsyncSessionLocal() as session:
            user = await session.get(User, registered_field_worker["id"])

        assert user.status == UserStatus.ACTIVE

    async def test_empty_selection_leaves_requests_pending(
        self, client, admin_headers, registered_field_worker, db_establishment
    ):
        """Approving with an empty selection must not resolve any request."""
        url = APPROVE_FIELD_WORKER_URL.format(user_id=registered_field_worker["id"])
        response = await client.patch(
            url, json={"establishment_ids": []}, headers=admin_headers
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

        async with db_module.AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserEstablishment).where(
                    UserEstablishment.establishment_id == db_establishment.id
                )
            )
            relation = result.scalar_one()

        assert relation.status.value == "pending"

    async def test_establishments_can_be_approved_afterwards(
        self, client, admin_headers, accepted_field_worker, db_establishment
    ):
        """The establishment flow keeps working once the user is accepted."""
        response = await client.patch(
            APPROVE_URL.format(user_id=accepted_field_worker["id"]),
            json={"establishment_ids": [str(db_establishment.id)]},
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        async with db_module.AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserEstablishment).where(
                    UserEstablishment.establishment_id == db_establishment.id
                )
            )
            relation = result.scalar_one()
        assert relation.status.value == "approved"

    async def test_no_establishments_still_becomes_active(self, client, admin_headers):
        """A field worker without requests can still be let in."""
        user_id = await _insert_user(
            UserRole.FIELD_WORKER, UserStatus.PENDING_VALIDATION
        )
        url = APPROVE_FIELD_WORKER_URL.format(user_id=user_id)

        response = await client.patch(
            url, json={"establishment_ids": []}, headers=admin_headers
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        async with db_module.AsyncSessionLocal() as session:
            user = await session.get(User, user_id)
        assert user.status == UserStatus.ACTIVE

    async def test_approves_only_the_selected_establishments(
        self, client, admin_headers, db_establishment, db_establishment_2
    ):
        """The admin accepts the account and picks a subset; the rest stay
        pending for a later decision."""
        register = await client.post(
            REGISTER_FIELD_WORKER_URL,
            json={
                "email": f"field_worker_{uuid.uuid4().hex[:6]}@test.com",
                "password": "Password123!",
                "name": "Test",
                "last_name": "Field Worker",
                "establishments": [
                    str(db_establishment.id),
                    str(db_establishment_2.id),
                ],
            },
        )
        assert register.status_code == status.HTTP_201_CREATED
        user_id = register.json()["id"]

        response = await client.patch(
            APPROVE_FIELD_WORKER_URL.format(user_id=user_id),
            json={"establishment_ids": [str(db_establishment.id)]},
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        async with db_module.AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserEstablishment).where(
                    UserEstablishment.user_id == uuid.UUID(user_id)
                )
            )
            by_establishment = {
                r.establishment_id: r.status.value for r in result.scalars()
            }

        assert by_establishment[db_establishment.id] == "approved"
        assert by_establishment[db_establishment_2.id] == "pending"

    async def test_unrequested_establishment_returns_404(
        self, client, admin_headers, registered_field_worker
    ):
        """The admin cannot approve an establishment the worker never asked for."""
        url = APPROVE_FIELD_WORKER_URL.format(user_id=registered_field_worker["id"])
        response = await client.patch(
            url,
            json={"establishment_ids": [str(uuid.uuid4())]},
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        async with db_module.AsyncSessionLocal() as session:
            user = await session.get(User, registered_field_worker["id"])
        assert user.status == UserStatus.PENDING_VALIDATION

    async def test_user_not_found_returns_404(self, client, admin_headers):
        """Should return 404 if the field worker does not exist."""
        url = APPROVE_FIELD_WORKER_URL.format(user_id=uuid.uuid4())
        response = await client.patch(
            url, json={"establishment_ids": []}, headers=admin_headers
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_registers_without_establishments_then_gets_approved(
        self, client, admin_headers
    ):
        """End to end: sign up with no establishments and still be let in."""
        register_response = await client.post(
            REGISTER_FIELD_WORKER_URL,
            json={
                "email": f"field_worker_{uuid.uuid4().hex[:6]}@test.com",
                "password": "Password123!",
                "name": "Test",
                "last_name": "Field Worker",
            },
        )
        assert register_response.status_code == status.HTTP_201_CREATED
        user_id = register_response.json()["id"]

        response = await client.patch(
            APPROVE_FIELD_WORKER_URL.format(user_id=user_id),
            json={"establishment_ids": []},
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        async with db_module.AsyncSessionLocal() as session:
            user = await session.get(User, user_id)
        assert user.status == UserStatus.ACTIVE

    async def test_active_field_worker_returns_400(self, client, admin_headers):
        """Only pending field workers can be approved."""
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        url = APPROVE_FIELD_WORKER_URL.format(user_id=user_id)

        response = await client.patch(
            url, json={"establishment_ids": []}, headers=admin_headers
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_non_field_worker_returns_400(self, client, admin_headers):
        """A pending admin invite must not be activated through this endpoint."""
        user_id = await _insert_user(UserRole.ADMIN, UserStatus.PENDING_VALIDATION)
        url = APPROVE_FIELD_WORKER_URL.format(user_id=user_id)

        response = await client.patch(
            url, json={"establishment_ids": []}, headers=admin_headers
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        async with db_module.AsyncSessionLocal() as session:
            user = await session.get(User, user_id)
        assert user.status == UserStatus.PENDING_VALIDATION


class TestRejectFieldWorker:
    async def test_returns_no_content(
        self, client, admin_headers, registered_field_worker, db_establishment
    ):
        """Should return 204 on successful rejection."""
        url = REJECT_FIELD_WORKER_URL.format(user_id=registered_field_worker["id"])
        response = await client.patch(url, headers=admin_headers)
        assert response.status_code == status.HTTP_204_NO_CONTENT

    async def test_field_worker_status_becomes_inactive(
        self, client, admin_headers, registered_field_worker
    ):
        """Field worker status should be INACTIVE after rejection."""
        url = REJECT_FIELD_WORKER_URL.format(user_id=registered_field_worker["id"])
        await client.patch(url, headers=admin_headers)

        list_response = await client.get(
            f"{ADMIN_USERS_URL}?page_size=100", headers=admin_headers
        )
        users = list_response.json()["items"]
        field_worker = next(
            u for u in users if u["id"] == registered_field_worker["id"]
        )
        assert field_worker["status"] == UserStatus.INACTIVE

    async def test_all_establishments_become_rejected(
        self, client, admin_headers, registered_field_worker, db_establishment
    ):
        """All user-establishment relations should be REJECTED in the database."""
        url = REJECT_FIELD_WORKER_URL.format(user_id=registered_field_worker["id"])
        await client.patch(url, headers=admin_headers)

        async with db_module.AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserEstablishment).where(
                    UserEstablishment.establishment_id == db_establishment.id
                )
            )
            relation = result.scalar_one()
        assert relation.status.value == "rejected"

    async def test_no_establishments_becomes_inactive(self, client, admin_headers, app):
        """A field worker with no establishments should still be marked INACTIVE."""
        user_id = await _insert_user(
            UserRole.FIELD_WORKER, UserStatus.PENDING_VALIDATION
        )
        url = REJECT_FIELD_WORKER_URL.format(user_id=user_id)
        response = await client.patch(url, headers=admin_headers)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        list_response = await client.get(
            f"{ADMIN_USERS_URL}?page_size=100", headers=admin_headers
        )
        users = list_response.json()["items"]
        field_worker = next(u for u in users if u["id"] == str(user_id))
        assert field_worker["status"] == UserStatus.INACTIVE

    async def test_active_field_worker_returns_400(self, client, admin_headers, app):
        """Should return 400 if the field worker is already active (use a dedicated
        revoke endpoint instead)."""
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        url = REJECT_FIELD_WORKER_URL.format(user_id=user_id)
        response = await client.patch(url, headers=admin_headers)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_user_not_found(self, client, admin_headers):
        """Should return 404 if the field worker does not exist."""
        url = REJECT_FIELD_WORKER_URL.format(user_id=uuid.uuid4())
        response = await client.patch(url, headers=admin_headers)
        assert response.status_code == status.HTTP_404_NOT_FOUND
