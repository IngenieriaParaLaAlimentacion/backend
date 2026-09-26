import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select

import app.db.database as db_module
from app.core.security import create_access_token
from app.domain.establishment import UserEstablishmentStatus
from app.domain.user import UserRole, UserStatus
from app.models.auth.user import User
from app.models.auth.user_establishment import UserEstablishment
from app.models.establishments.establishment import Establishment

ME_URL = "/api/v1/users/me"
ME_ESTABLISHMENTS_URL = "/api/v1/users/me/establishments"
ME_ESTABLISHMENTS_WITHDRAW_URL = "/api/v1/users/me/establishments/withdraw"


async def _insert_user(
    *,
    role: UserRole,
    status: UserStatus = UserStatus.ACTIVE,
    name: str = "Test",
    last_name: str = "User",
    email: str | None = None,
) -> SimpleNamespace:
    """Insert a user and return its fields (id resolved)."""
    user_id = uuid.uuid4()
    resolved_email = email or f"{user_id}@test.com"
    async with db_module.AsyncSessionLocal() as session:
        session.add(
            User(
                id=user_id,
                name=name,
                last_name=last_name,
                email=resolved_email,
                role=role,
                status=status,
            )
        )
        await session.commit()
    return SimpleNamespace(
        id=user_id,
        name=name,
        last_name=last_name,
        email=resolved_email,
        role=role,
        status=status,
    )


async def _insert_establishment(name: str, formatted_address: str) -> SimpleNamespace:
    establishment = Establishment(
        name=name,
        formatted_address=formatted_address,
        latitude=-34.6037,
        longitude=-58.3816,
        place_id=str(uuid.uuid4()),
        city="Buenos Aires",
        province="Buenos Aires",
    )
    async with db_module.AsyncSessionLocal() as session:
        session.add(establishment)
        await session.commit()
        await session.refresh(establishment)
    return SimpleNamespace(
        id=establishment.id, name=name, formatted_address=formatted_address
    )


async def _insert_relation(
    user_id: uuid.UUID,
    establishment_id: uuid.UUID,
    status: UserEstablishmentStatus,
) -> None:
    async with db_module.AsyncSessionLocal() as session:
        session.add(
            UserEstablishment(
                user_id=user_id,
                establishment_id=establishment_id,
                status=status,
            )
        )
        await session.commit()


def _headers_for(user: SimpleNamespace) -> dict:
    token = create_access_token(user.id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


async def _fetch_user(user_id: uuid.UUID) -> User | None:
    async with db_module.AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()


async def _fetch_relations(user_id: uuid.UUID) -> list[UserEstablishment]:
    async with db_module.AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserEstablishment).where(UserEstablishment.user_id == user_id)
        )
        return list(result.scalars().all())


@pytest_asyncio.fixture
async def analyst_user(app):
    return await _insert_user(role=UserRole.ANALYST, status=UserStatus.ACTIVE)


@pytest_asyncio.fixture
async def admin_user(app):
    return await _insert_user(role=UserRole.ADMIN, status=UserStatus.ACTIVE)


@pytest_asyncio.fixture
async def field_worker_user(app):
    return await _insert_user(role=UserRole.FIELD_WORKER, status=UserStatus.ACTIVE)


class TestProfileAuth:
    async def test_no_token_returns_401(self, client):
        """Should return 401 when no access token is provided."""
        response = await client.get(ME_URL)
        assert response.status_code == 401

    async def test_malformed_token_returns_401(self, client):
        """Should return 401 when the token is not a valid JWT."""
        response = await client.get(
            ME_URL, headers={"Authorization": "Bearer not_a_jwt"}
        )
        assert response.status_code == 401


class TestProfileNonFieldWorker:
    async def test_analyst_has_null_establishments(self, client, analyst_user):
        """An analyst gets their profile with establishments = null."""
        response = await client.get(ME_URL, headers=_headers_for(analyst_user))

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(analyst_user.id)
        assert body["email"] == analyst_user.email
        assert body["name"] == analyst_user.name
        assert body["last_name"] == analyst_user.last_name
        assert body["role"] == UserRole.ANALYST
        assert body["establishments"] is None

    async def test_admin_has_null_establishments(self, client, admin_user):
        """An admin gets their profile with establishments = null."""
        response = await client.get(ME_URL, headers=_headers_for(admin_user))

        assert response.status_code == 200
        body = response.json()
        assert body["role"] == UserRole.ADMIN
        assert body["establishments"] is None


class TestProfileFieldWorker:
    async def test_field_worker_with_establishments_lists_status(
        self, client, field_worker_user
    ):
        """A field worker receives each establishment annotated with its status."""
        estab_a = await _insert_establishment("Centro A", "Calle A 123")
        estab_b = await _insert_establishment("Centro B", "Calle B 456")
        await _insert_relation(
            field_worker_user.id, estab_a.id, UserEstablishmentStatus.APPROVED
        )
        await _insert_relation(
            field_worker_user.id, estab_b.id, UserEstablishmentStatus.PENDING
        )

        response = await client.get(ME_URL, headers=_headers_for(field_worker_user))

        assert response.status_code == 200
        body = response.json()
        assert body["role"] == UserRole.FIELD_WORKER
        establishments = body["establishments"]
        assert establishments is not None
        assert len(establishments) == 2

        by_id = {item["id"]: item for item in establishments}
        item_a = by_id[str(estab_a.id)]
        assert item_a["name"] == "Centro A"
        assert item_a["formatted_address"] == "Calle A 123"
        assert item_a["status"] == UserEstablishmentStatus.APPROVED

        item_b = by_id[str(estab_b.id)]
        assert item_b["status"] == UserEstablishmentStatus.PENDING

    async def test_field_worker_with_no_establishments_returns_empty_list(
        self, client, field_worker_user
    ):
        """A field worker with no relations gets an empty list (not null)."""
        response = await client.get(ME_URL, headers=_headers_for(field_worker_user))

        assert response.status_code == 200
        assert response.json()["establishments"] == []


class TestProfileMissingUser:
    async def test_valid_token_for_unknown_user_returns_404(self, client, app):
        """A valid token whose user was never persisted returns 404."""
        ghost = SimpleNamespace(id=uuid.uuid4(), role=UserRole.ANALYST)
        response = await client.get(ME_URL, headers=_headers_for(ghost))
        assert response.status_code == 404


class TestProfileEdit:
    async def test_analyst_edits_both_fields(self, client, analyst_user):
        """CA1: editing name and last_name returns 200 and persists the change."""
        response = await client.patch(
            ME_URL,
            json={"name": "Juana", "last_name": "Perez"},
            headers=_headers_for(analyst_user),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Juana"
        assert body["last_name"] == "Perez"
        assert body["email"] == analyst_user.email

        reread = await client.get(ME_URL, headers=_headers_for(analyst_user))
        assert reread.json()["name"] == "Juana"
        assert reread.json()["last_name"] == "Perez"

    async def test_partial_edit_leaves_other_field_unchanged(
        self, client, analyst_user
    ):
        """CA1: sending only ``name`` leaves ``last_name`` untouched."""
        response = await client.patch(
            ME_URL,
            json={"name": "SoloNombre"},
            headers=_headers_for(analyst_user),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "SoloNombre"
        assert body["last_name"] == analyst_user.last_name

    async def test_empty_name_returns_422_and_keeps_db(self, client, analyst_user):
        """An empty name fails validation (422) and persists nothing."""
        response = await client.patch(
            ME_URL, json={"name": ""}, headers=_headers_for(analyst_user)
        )

        assert response.status_code == 422
        stored = await _fetch_user(analyst_user.id)
        assert stored.name == analyst_user.name

    async def test_empty_body_returns_400(self, client, analyst_user):
        """A defined-but-empty body is rejected by the service (400)."""
        response = await client.patch(
            ME_URL, json={}, headers=_headers_for(analyst_user)
        )

        assert response.status_code == 400

    @pytest.mark.parametrize(
        "payload",
        [
            {"email": "new@test.com"},
            {"role": "admin"},
            {"status": "active"},
        ],
    )
    async def test_non_editable_fields_return_422_and_keep_db(
        self, client, analyst_user, payload
    ):
        """editing email/role/status (or any unknown field) is rejected (422)."""
        response = await client.patch(
            ME_URL, json=payload, headers=_headers_for(analyst_user)
        )

        assert response.status_code == 422
        stored = await _fetch_user(analyst_user.id)
        assert stored.email == analyst_user.email
        assert stored.role == analyst_user.role
        assert stored.status == analyst_user.status

    async def test_field_worker_edit_still_returns_establishments(
        self, client, field_worker_user
    ):
        """CA1: a field worker's edit response still includes their establishments."""
        estab = await _insert_establishment("Centro A", "Calle A 123")
        await _insert_relation(
            field_worker_user.id, estab.id, UserEstablishmentStatus.APPROVED
        )

        response = await client.patch(
            ME_URL,
            json={"name": "NuevoNombre"},
            headers=_headers_for(field_worker_user),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "NuevoNombre"
        establishments = body["establishments"]
        assert establishments is not None
        assert len(establishments) == 1
        assert establishments[0]["id"] == str(estab.id)
        assert establishments[0]["status"] == UserEstablishmentStatus.APPROVED

    async def test_no_token_returns_401(self, client):
        """CA7: no token returns 401."""
        response = await client.patch(ME_URL, json={"name": "X"})
        assert response.status_code == 401

    async def test_malformed_token_returns_401(self, client):
        """CA7: a malformed token returns 401."""
        response = await client.patch(
            ME_URL, json={"name": "X"}, headers={"Authorization": "Bearer not_a_jwt"}
        )
        assert response.status_code == 401


class TestListOwnEstablishments:
    async def test_field_worker_lists_relations_with_status(
        self, client, field_worker_user
    ):
        """A field worker receives their relations annotated with status."""
        estab_a = await _insert_establishment("Centro A", "Calle A")
        estab_b = await _insert_establishment("Centro B", "Calle B")
        await _insert_relation(
            field_worker_user.id, estab_a.id, UserEstablishmentStatus.APPROVED
        )
        await _insert_relation(
            field_worker_user.id, estab_b.id, UserEstablishmentStatus.REJECTED
        )

        response = await client.get(
            ME_ESTABLISHMENTS_URL, headers=_headers_for(field_worker_user)
        )

        assert response.status_code == 200
        by_id = {item["id"]: item for item in response.json()}
        assert by_id[str(estab_a.id)]["name"] == "Centro A"
        assert by_id[str(estab_a.id)]["status"] == UserEstablishmentStatus.APPROVED
        assert by_id[str(estab_b.id)]["status"] == UserEstablishmentStatus.REJECTED

    async def test_field_worker_with_no_relations_returns_empty(
        self, client, field_worker_user
    ):
        response = await client.get(
            ME_ESTABLISHMENTS_URL, headers=_headers_for(field_worker_user)
        )
        assert response.status_code == 200
        assert response.json() == []

    async def test_no_token_returns_401(self, client):
        response = await client.get(ME_ESTABLISHMENTS_URL)
        assert response.status_code == 401


class TestRequestEstablishmentAccess:
    async def test_new_ids_create_pending_relations(self, client, field_worker_user):
        """CA5: requesting new establishments creates pending relations."""
        estab_a = await _insert_establishment("Centro A", "Calle A")
        estab_b = await _insert_establishment("Centro B", "Calle B")

        response = await client.post(
            ME_ESTABLISHMENTS_URL,
            json={"establishment_ids": [str(estab_a.id), str(estab_b.id)]},
            headers=_headers_for(field_worker_user),
        )

        assert response.status_code == 201
        by_id = {item["id"]: item for item in response.json()}
        assert by_id[str(estab_a.id)]["status"] == UserEstablishmentStatus.PENDING
        assert by_id[str(estab_b.id)]["status"] == UserEstablishmentStatus.PENDING

        relations = await _fetch_relations(field_worker_user.id)
        assert {r.establishment_id for r in relations} == {estab_a.id, estab_b.id}
        assert all(r.status == UserEstablishmentStatus.PENDING for r in relations)

    async def test_rejected_relation_is_re_requested(self, client, field_worker_user):
        """CA5/CA6: a rejected relation can be re-requested (back to pending)."""
        estab = await _insert_establishment("Centro A", "Calle A")
        await _insert_relation(
            field_worker_user.id, estab.id, UserEstablishmentStatus.REJECTED
        )

        response = await client.post(
            ME_ESTABLISHMENTS_URL,
            json={"establishment_ids": [str(estab.id)]},
            headers=_headers_for(field_worker_user),
        )

        assert response.status_code == 201
        assert response.json()[0]["status"] == UserEstablishmentStatus.PENDING

        relations = await _fetch_relations(field_worker_user.id)
        assert len(relations) == 1
        assert relations[0].status == UserEstablishmentStatus.PENDING

    async def test_revoked_relation_is_re_requested(self, client, field_worker_user):
        """A revoked relation can be re-requested (back to pending), same as
        a rejected one."""
        estab = await _insert_establishment("Centro A", "Calle A")
        await _insert_relation(
            field_worker_user.id, estab.id, UserEstablishmentStatus.REVOKED
        )

        response = await client.post(
            ME_ESTABLISHMENTS_URL,
            json={"establishment_ids": [str(estab.id)]},
            headers=_headers_for(field_worker_user),
        )

        assert response.status_code == 201
        assert response.json()[0]["status"] == UserEstablishmentStatus.PENDING

        relations = await _fetch_relations(field_worker_user.id)
        assert len(relations) == 1
        assert relations[0].status == UserEstablishmentStatus.PENDING

    async def test_approved_stays_and_new_becomes_pending(
        self, client, field_worker_user
    ):
        """CA6: an approved relation is untouched while a new one is created."""
        approved = await _insert_establishment("Approved", "Addr 1")
        new = await _insert_establishment("New", "Addr 2")
        await _insert_relation(
            field_worker_user.id, approved.id, UserEstablishmentStatus.APPROVED
        )

        response = await client.post(
            ME_ESTABLISHMENTS_URL,
            json={"establishment_ids": [str(approved.id), str(new.id)]},
            headers=_headers_for(field_worker_user),
        )

        assert response.status_code == 201
        by_id = {item["id"]: item for item in response.json()}
        assert by_id[str(approved.id)]["status"] == UserEstablishmentStatus.APPROVED
        assert by_id[str(new.id)]["status"] == UserEstablishmentStatus.PENDING

        relations = await _fetch_relations(field_worker_user.id)
        assert len(relations) == 2  # no duplicate rows
        status_by_id = {r.establishment_id: r.status for r in relations}
        assert status_by_id[approved.id] == UserEstablishmentStatus.APPROVED
        assert status_by_id[new.id] == UserEstablishmentStatus.PENDING

    async def test_pending_stays_single_row(self, client, field_worker_user):
        """CA6: re-requesting a pending relation keeps a single pending row."""
        estab = await _insert_establishment("Centro A", "Calle A")
        await _insert_relation(
            field_worker_user.id, estab.id, UserEstablishmentStatus.PENDING
        )

        response = await client.post(
            ME_ESTABLISHMENTS_URL,
            json={"establishment_ids": [str(estab.id)]},
            headers=_headers_for(field_worker_user),
        )

        assert response.status_code == 201
        assert response.json()[0]["status"] == UserEstablishmentStatus.PENDING

        relations = await _fetch_relations(field_worker_user.id)
        assert len(relations) == 1
        assert relations[0].status == UserEstablishmentStatus.PENDING

    async def test_unknown_establishment_returns_404_and_writes_nothing(
        self, client, field_worker_user
    ):
        response = await client.post(
            ME_ESTABLISHMENTS_URL,
            json={"establishment_ids": [str(uuid.uuid4())]},
            headers=_headers_for(field_worker_user),
        )

        assert response.status_code == 404
        assert await _fetch_relations(field_worker_user.id) == []

    async def test_no_token_returns_401(self, client):
        """CA7: no token returns 401."""
        response = await client.post(
            ME_ESTABLISHMENTS_URL, json={"establishment_ids": [str(uuid.uuid4())]}
        )
        assert response.status_code == 401


class TestWithdrawEstablishmentAccess:
    async def test_approved_relation_is_withdrawn(self, client, field_worker_user):
        estab = await _insert_establishment("Centro A", "Calle A")
        await _insert_relation(
            field_worker_user.id, estab.id, UserEstablishmentStatus.APPROVED
        )

        response = await client.patch(
            ME_ESTABLISHMENTS_WITHDRAW_URL,
            json={"establishment_ids": [str(estab.id)]},
            headers=_headers_for(field_worker_user),
        )

        assert response.status_code == 200
        assert response.json()[0]["status"] == UserEstablishmentStatus.WITHDRAWN

        relations = await _fetch_relations(field_worker_user.id)
        assert len(relations) == 1
        assert relations[0].status == UserEstablishmentStatus.WITHDRAWN

    async def test_pending_relation_is_withdrawn(self, client, field_worker_user):
        estab = await _insert_establishment("Centro A", "Calle A")
        await _insert_relation(
            field_worker_user.id, estab.id, UserEstablishmentStatus.PENDING
        )

        response = await client.patch(
            ME_ESTABLISHMENTS_WITHDRAW_URL,
            json={"establishment_ids": [str(estab.id)]},
            headers=_headers_for(field_worker_user),
        )

        assert response.status_code == 200
        relations = await _fetch_relations(field_worker_user.id)
        assert relations[0].status == UserEstablishmentStatus.WITHDRAWN

    async def test_rejected_relation_returns_409_and_writes_nothing(
        self, client, field_worker_user
    ):
        estab = await _insert_establishment("Centro A", "Calle A")
        await _insert_relation(
            field_worker_user.id, estab.id, UserEstablishmentStatus.REJECTED
        )

        response = await client.patch(
            ME_ESTABLISHMENTS_WITHDRAW_URL,
            json={"establishment_ids": [str(estab.id)]},
            headers=_headers_for(field_worker_user),
        )

        assert response.status_code == 409
        relations = await _fetch_relations(field_worker_user.id)
        assert relations[0].status == UserEstablishmentStatus.REJECTED

    async def test_unknown_establishment_returns_404_and_writes_nothing(
        self, client, field_worker_user
    ):
        response = await client.patch(
            ME_ESTABLISHMENTS_WITHDRAW_URL,
            json={"establishment_ids": [str(uuid.uuid4())]},
            headers=_headers_for(field_worker_user),
        )

        assert response.status_code == 404
        assert await _fetch_relations(field_worker_user.id) == []

    async def test_no_token_returns_401(self, client):
        response = await client.patch(
            ME_ESTABLISHMENTS_WITHDRAW_URL,
            json={"establishment_ids": [str(uuid.uuid4())]},
        )
        assert response.status_code == 401
