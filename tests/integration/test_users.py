import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio

import app.db.database as db_module
from app.core.security import create_access_token
from app.domain.establishment import UserEstablishmentStatus
from app.domain.user import UserRole, UserStatus
from app.models.establishment import Establishment
from app.models.user import User
from app.models.user_establishment import UserEstablishment

pytestmark = pytest.mark.asyncio

ME_URL = "/api/v1/users/me"


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


async def _insert_establishment(name: str, address: str) -> SimpleNamespace:
    establishment = Establishment(name=name, address=address)
    async with db_module.AsyncSessionLocal() as session:
        session.add(establishment)
        await session.commit()
        await session.refresh(establishment)
    return SimpleNamespace(id=establishment.id, name=name, address=address)


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


@pytest_asyncio.fixture
async def professional_user(app):
    return await _insert_user(role=UserRole.PROFESSIONAL, status=UserStatus.ACTIVE)


@pytest_asyncio.fixture
async def admin_user(app):
    return await _insert_user(role=UserRole.ADMIN, status=UserStatus.ACTIVE)


@pytest_asyncio.fixture
async def manager_user(app):
    return await _insert_user(
        role=UserRole.ESTABLISHMENT_MANAGER, status=UserStatus.ACTIVE
    )


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


class TestProfileNonManager:
    async def test_professional_has_null_establishments(
        self, client, professional_user
    ):
        """A professional gets their profile with establishments = null."""
        response = await client.get(ME_URL, headers=_headers_for(professional_user))

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(professional_user.id)
        assert body["email"] == professional_user.email
        assert body["name"] == professional_user.name
        assert body["last_name"] == professional_user.last_name
        assert body["role"] == UserRole.PROFESSIONAL
        assert body["establishments"] is None

    async def test_admin_has_null_establishments(self, client, admin_user):
        """An admin gets their profile with establishments = null."""
        response = await client.get(ME_URL, headers=_headers_for(admin_user))

        assert response.status_code == 200
        body = response.json()
        assert body["role"] == UserRole.ADMIN
        assert body["establishments"] is None


class TestProfileManager:
    async def test_manager_with_establishments_lists_status(self, client, manager_user):
        """A manager receives each establishment annotated with its status."""
        estab_a = await _insert_establishment("Centro A", "Calle A 123")
        estab_b = await _insert_establishment("Centro B", "Calle B 456")
        await _insert_relation(
            manager_user.id, estab_a.id, UserEstablishmentStatus.APPROVED
        )
        await _insert_relation(
            manager_user.id, estab_b.id, UserEstablishmentStatus.PENDING
        )

        response = await client.get(ME_URL, headers=_headers_for(manager_user))

        assert response.status_code == 200
        body = response.json()
        assert body["role"] == UserRole.ESTABLISHMENT_MANAGER
        establishments = body["establishments"]
        assert establishments is not None
        assert len(establishments) == 2

        by_id = {item["id"]: item for item in establishments}
        item_a = by_id[str(estab_a.id)]
        assert item_a["name"] == "Centro A"
        assert item_a["address"] == "Calle A 123"
        assert item_a["status"] == UserEstablishmentStatus.APPROVED

        item_b = by_id[str(estab_b.id)]
        assert item_b["status"] == UserEstablishmentStatus.PENDING

    async def test_manager_with_no_establishments_returns_empty_list(
        self, client, manager_user
    ):
        """A manager with no relations gets an empty list (not null)."""
        response = await client.get(ME_URL, headers=_headers_for(manager_user))

        assert response.status_code == 200
        assert response.json()["establishments"] == []


class TestProfileMissingUser:
    async def test_valid_token_for_unknown_user_returns_404(self, client, app):
        """A valid token whose user was never persisted returns 404."""
        ghost = SimpleNamespace(id=uuid.uuid4(), role=UserRole.PROFESSIONAL)
        response = await client.get(ME_URL, headers=_headers_for(ghost))
        assert response.status_code == 404
