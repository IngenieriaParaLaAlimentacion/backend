import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest_asyncio

from app.core.security import create_access_token
from app.domain.user import UserRole

URL = "/api/v1/food-intakes/from-photo/confirm"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest_asyncio.fixture
async def db_admin_headers(app):
    """A real admin user in the DB, needed because confirming an intake
    writes responsible_id -- a plain (unpersisted) actor would violate the
    food_intakes_responsible_id_fkey constraint."""
    from app.db.database import AsyncSessionLocal
    from app.domain.user import UserStatus
    from app.models.auth.user import User
    from app.models.auth.user import UserRole as ORMUserRole

    user_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        session.add(
            User(
                id=user_id,
                name="Admin",
                last_name="Test",
                email=f"{user_id}@test.com",
                role=ORMUserRole.ADMIN,
                status=UserStatus.ACTIVE,
            )
        )
        await session.commit()

    token = create_access_token(user_id, role=UserRole.ADMIN)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def rice_food_id(app) -> uuid.UUID:
    """Seed one catalog food. The catalog has no create endpoint."""
    from app.db.database import AsyncSessionLocal
    from app.domain.food_catalog import MeasurementUnit
    from app.models.food_catalog.food import Food
    from app.models.food_catalog.food_category import FoodCategory

    async with AsyncSessionLocal() as session:
        cereals = FoodCategory(code="cereales", name="Cereales")
        session.add(cereals)
        await session.flush()

        rice = Food(
            code="arroz",
            name="Arroz",
            category_id=cereals.id,
            base_unit=MeasurementUnit.KILOGRAMOS,
        )
        session.add(rice)
        await session.commit()
        return rice.id


def _confirm_payload(establishment_id, food_id, **overrides) -> dict:
    fields = {
        "establishment_id": str(establishment_id),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "source": "photo",
        "items": [{"food_id": str(food_id), "quantity": "2.5"}],
        **overrides,
    }
    return fields


def _multipart(payload: dict):
    return {
        "data": {"data": json.dumps(payload)},
        "files": {"image": ("receipt.png", PNG_BYTES, "image/png")},
    }


class TestConfirmFromPhoto:
    async def test_confirm_saves_photo_and_creates_the_intake(
        self, client, db_admin_headers, db_establishment, rice_food_id
    ):
        payload = _confirm_payload(db_establishment.id, rice_food_id)

        response = await client.post(
            URL, headers=db_admin_headers, **_multipart(payload)
        )

        assert response.status_code == 201
        body = response.json()
        assert body["source"] == "photo"
        assert body["photo_key"].startswith(
            f"food-intake-receipts/{db_establishment.id}/"
        )
        assert body["photo_key"].endswith(".png")
        assert len(body["items"]) == 1
        assert body["items"][0]["food"]["id"] == str(rice_food_id)
        assert Decimal(body["items"][0]["quantity"]) == Decimal("2.500")

    async def test_replaying_the_same_id_does_not_reupload_the_photo(
        self, client, db_admin_headers, db_establishment, rice_food_id
    ):
        payload = _confirm_payload(
            db_establishment.id, rice_food_id, id=str(uuid.uuid4())
        )

        first = await client.post(URL, headers=db_admin_headers, **_multipart(payload))
        second = await client.post(URL, headers=db_admin_headers, **_multipart(payload))

        assert first.status_code == 201
        assert second.status_code == 200
        # Same row, same photo -- a retry must not have uploaded a second,
        # now orphaned, copy under a fresh key.
        assert first.json()["photo_key"] == second.json()["photo_key"]
        assert first.json()["id"] == second.json()["id"]

    async def test_unknown_establishment_returns_404(self, client, admin_headers):
        payload = _confirm_payload(uuid.uuid4(), uuid.uuid4())

        response = await client.post(URL, headers=admin_headers, **_multipart(payload))

        assert response.status_code == 404

    async def test_missing_token_is_rejected(
        self, client, db_establishment, rice_food_id
    ):
        payload = _confirm_payload(db_establishment.id, rice_food_id)

        response = await client.post(URL, **_multipart(payload))

        assert response.status_code == 401

    async def test_malformed_data_field_is_rejected_with_422(
        self, client, admin_headers, db_establishment
    ):
        response = await client.post(
            URL,
            headers=admin_headers,
            data={"data": "not valid json"},
            files={"image": ("receipt.png", PNG_BYTES, "image/png")},
        )

        assert response.status_code == 422
        assert response.json()["type"] == "/errors/validation-failed"
