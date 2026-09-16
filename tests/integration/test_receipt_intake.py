import uuid

import pytest

from app.config.settings import settings
from app.exceptions.domain_exceptions import LlmClientError

pytestmark = pytest.mark.asyncio

URL = "/api/v1/food-intakes/from-photo"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _upload(establishment_id, *, filename="receipt.png", content_type="image/png"):
    return {
        "data": {"establishment_id": str(establishment_id)},
        "files": {"image": (filename, PNG_BYTES, content_type)},
    }


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

    async def test_detected_items_are_returned_needing_review(
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
        assert all(line["needs_review"] for line in body["lines"])
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

    async def test_missing_file_is_rejected_by_framework_validation(
        self, client, admin_headers, db_establishment
    ):
        response = await client.post(
            URL,
            headers=admin_headers,
            data={"establishment_id": str(db_establishment.id)},
        )

        assert response.status_code == 422
        assert response.json()["type"] == "/errors/validation-failed"


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
