import uuid

import pytest
from fastapi import status
from jose import jwt

from app.core.security import create_access_token
from app.domain.user import UserRole

pytestmark = pytest.mark.asyncio


class TestAdminAuth:
    async def test_unauthenticated(self, client, any_admin_request):
        """Should return 401 if no access token is provided."""
        response = await any_admin_request(client)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_malformed_token(self, client, any_admin_request):
        """Should return 401 if the token is not a valid JWT."""
        response = await any_admin_request(
            client, headers={"Authorization": "Bearer token_invalido"}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_token_signed_with_wrong_secret(self, client, any_admin_request):
        """Should return 401 if the token is signed with the wrong secret."""
        payload = {"sub": str(uuid.uuid4()), "role": "admin", "type": "access"}
        forged_token = jwt.encode(payload, "secret_field_worker", algorithm="HS256")
        response = await any_admin_request(
            client, headers={"Authorization": f"Bearer {forged_token}"}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_field_worker_is_forbidden(self, client, any_admin_request):
        """Should return 403 when a valid field worker token is provided."""
        token = create_access_token(uuid.uuid4(), role=UserRole.FIELD_WORKER)
        response = await any_admin_request(
            client, headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_analyst_is_forbidden(self, client, any_admin_request):
        """Should return 403 when a valid analyst token is provided."""
        token = create_access_token(uuid.uuid4(), role=UserRole.ANALYST)
        response = await any_admin_request(
            client, headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
