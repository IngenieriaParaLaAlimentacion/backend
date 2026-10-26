import uuid

import pytest
import pytest_asyncio

from app.config.settings import settings
from app.exceptions.domain_exceptions import (
    LlmClientError,
    LlmQuotaExhaustedError,
    LlmUnavailableError,
)

URL = "/api/v1/food-intakes/from-photo"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _upload(establishment_id, *, filename="receipt.png", content_type="image/png"):
    return {
        "data": {"establishment_id": str(establishment_id)},
        "files": {"image": (filename, PNG_BYTES, content_type)},
    }


@pytest_asyncio.fixture
async def db_food(app):
    """Seed a single real catalog food ("Arroz") to exercise trigram matching
    (ADR-0017) against a real Postgres instance, not a mock."""
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
        await session.refresh(rice)
        return rice


@pytest_asyncio.fixture
async def db_foods(app):
    """Seed a small, varied catalog to exercise the word-similarity + whole-string
    floor combination (ADR-0017) against a real Postgres instance.

    Includes "Sal" -- a short name that a naive word-similarity match would score
    deceptively high against an unrelated, noisy receipt line -- to prove the
    whole-string floor actually guards against that false positive.
    """
    from app.db.database import AsyncSessionLocal
    from app.domain.food_catalog import MeasurementUnit
    from app.models.food_catalog.food import Food
    from app.models.food_catalog.food_category import FoodCategory

    async with AsyncSessionLocal() as session:
        category = FoodCategory(code="varios", name="Varios")
        session.add(category)
        await session.flush()

        foods = {
            "ketchup": Food(
                code="ketchup",
                name="Ketchup",
                category_id=category.id,
                base_unit=MeasurementUnit.KILOGRAMOS,
            ),
            "sal": Food(
                code="sal",
                name="Sal",
                category_id=category.id,
                base_unit=MeasurementUnit.KILOGRAMOS,
            ),
        }
        session.add_all(foods.values())
        await session.commit()
        for food in foods.values():
            await session.refresh(food)
        return foods


class TestAcceptedUpload:
    async def test_no_items_detected_returns_manual_fallback_message(
        self, client, admin_headers, db_establishment, fake_llm_client
    ):
        response = await client.post(
            URL, headers=admin_headers, **_upload(db_establishment.id)
        )

        assert response.status_code == 200
        body = response.json()
        assert body["establishment_id"] == str(db_establishment.id)
        assert body["lines"] == []
        assert body["message"]

    async def test_detected_items_are_returned(
        self, client, admin_headers, db_establishment, fake_llm_client
    ):
        fake_llm_client.response = {
            "lines": [{"description": "Arroz 1kg"}, {"description": "Leche 1L"}]
        }

        response = await client.post(
            URL, headers=admin_headers, **_upload(db_establishment.id)
        )

        assert response.status_code == 200
        body = response.json()
        assert [line["description"] for line in body["lines"]] == [
            "Arroz 1kg",
            "Leche 1L",
        ]
        assert all(line["food"] is None for line in body["lines"])
        assert all("needs_review" not in line for line in body["lines"])
        assert body["message"] is None

    async def test_llm_failure_falls_back_to_manual_entry(
        self, client, admin_headers, db_establishment, fake_llm_client
    ):
        fake_llm_client.error = LlmClientError("gemini is down")

        response = await client.post(
            URL, headers=admin_headers, **_upload(db_establishment.id)
        )

        assert response.status_code == 200
        body = response.json()
        assert body["lines"] == []
        assert body["message"]

    async def test_field_worker_with_approved_access_can_upload(
        self, client, db_establishment, field_worker_with_access, fake_llm_client
    ):
        headers, _ = field_worker_with_access

        response = await client.post(
            URL, headers=headers, **_upload(db_establishment.id)
        )

        assert response.status_code == 200


class TestCatalogMatching:
    """Trigram-similarity matching against the real catalog (ADR-0017)."""

    async def test_close_description_matches_the_catalog_food(
        self, client, admin_headers, db_establishment, db_food, fake_llm_client
    ):
        fake_llm_client.response = {"lines": [{"description": "Arroz 1kg"}]}

        response = await client.post(
            URL, headers=admin_headers, **_upload(db_establishment.id)
        )

        assert response.status_code == 200
        (line,) = response.json()["lines"]
        assert line["food"] == {"id": str(db_food.id), "name": db_food.name}

    async def test_unrelated_description_leaves_food_null(
        self, client, admin_headers, db_establishment, db_food, fake_llm_client
    ):
        fake_llm_client.response = {"lines": [{"description": "Mute Santandereano"}]}

        response = await client.post(
            URL, headers=admin_headers, **_upload(db_establishment.id)
        )

        assert response.status_code == 200
        (line,) = response.json()["lines"]
        assert line["food"] is None

    async def test_brand_and_pack_size_noise_still_matches_the_catalog_food(
        self, client, admin_headers, db_establishment, db_foods, fake_llm_client
    ):
        """A real receipt line is far noisier than "Arroz 1kg": brand name and pack
        size surround the actual product name. Whole-string ``similarity`` dilutes
        to well under threshold on a line like this (the bug this test guards
        against); ``word_similarity`` isn't diluted by it."""
        fake_llm_client.response = {
            "lines": [{"description": "Ketchup HELLMANNS x250g DOY 237 gr."}]
        }

        response = await client.post(
            URL, headers=admin_headers, **_upload(db_establishment.id)
        )

        assert response.status_code == 200
        (line,) = response.json()["lines"]
        ketchup = db_foods["ketchup"]
        assert line["food"] == {"id": str(ketchup.id), "name": ketchup.name}

    async def test_short_catalog_name_does_not_false_positive_on_unrelated_noise(
        self, client, admin_headers, db_establishment, db_foods, fake_llm_client
    ):
        """``word_similarity`` alone can score a short catalog name like "Sal"
        deceptively high against a coincidental extent of unrelated, noisy text --
        the whole-string floor (``receipt_food_match_min_similarity``) must reject
        it anyway."""
        fake_llm_client.response = {
            "lines": [{"description": "Tapas para Tarta LA SALTENA Hojaldr 400"}]
        }

        response = await client.post(
            URL, headers=admin_headers, **_upload(db_establishment.id)
        )

        assert response.status_code == 200
        (line,) = response.json()["lines"]
        assert line["food"] is None


class TestImageValidation:
    async def test_unsupported_type_is_rejected_with_422(
        self, client, admin_headers, db_establishment
    ):
        response = await client.post(
            URL,
            headers=admin_headers,
            **_upload(
                db_establishment.id,
                filename="receipt.pdf",
                content_type="application/pdf",
            ),
        )

        assert response.status_code == 422
        body = response.json()
        assert body["type"] == "/errors/unsupported-image-type"
        assert "application/pdf" in body["detail"]

    async def test_oversized_image_is_rejected_with_422(
        self, client, admin_headers, db_establishment, monkeypatch
    ):
        monkeypatch.setattr(settings, "receipt_image_max_bytes", 8)

        response = await client.post(
            URL, headers=admin_headers, **_upload(db_establishment.id)
        )

        assert response.status_code == 422
        assert response.json()["type"] == "/errors/image-too-large"


class TestAuthAndAccess:
    async def test_missing_token_is_rejected(self, client, db_establishment):
        response = await client.post(URL, **_upload(db_establishment.id))

        assert response.status_code == 401
        assert response.json()["type"] == "/errors/auth/missing-token"

    async def test_field_worker_without_approved_access_is_forbidden(
        self, client, field_worker_headers, db_establishment
    ):
        response = await client.post(
            URL, headers=field_worker_headers, **_upload(db_establishment.id)
        )

        assert response.status_code == 403
        assert response.json()["type"] == "/errors/establishment-access-denied"

    async def test_unknown_establishment_returns_404(self, client, admin_headers):
        response = await client.post(
            URL, headers=admin_headers, **_upload(uuid.uuid4())
        )

        assert response.status_code == 404
        assert response.json()["type"] == "/errors/establishment-not-found"


@pytest.mark.parametrize(
    "failure,status,slug,delay",
    [
        (LlmQuotaExhaustedError(12), 429, "ai/quota-exhausted", 12),
        (LlmQuotaExhaustedError(), 429, "ai/quota-exhausted", None),
        (LlmUnavailableError("private provider failure"), 503, "ai/unavailable", None),
    ],
)
async def test_provider_errors_have_canonical_safe_contract(
    client,
    admin_headers,
    db_establishment,
    fake_llm_client,
    failure,
    status,
    slug,
    delay,
):
    fake_llm_client.error = failure
    response = await client.post(
        URL, headers=admin_headers, **_upload(db_establishment.id)
    )
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == f"/errors/{slug}"
    assert "private" not in response.text
    if delay:
        assert response.headers["retry-after"] == str(delay)
        assert response.json()["retry_after"] == delay
    else:
        assert "retry-after" not in response.headers
        assert "retry_after" not in response.json()
