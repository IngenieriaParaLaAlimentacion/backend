from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from jose import JWTError

from app.core.dependencies import require_admin, require_admin_or_analyst, require_any
from app.exceptions.domain_exceptions import (
    ForbiddenError,
    UnauthorizedError,
    UserBlockedError,
)
from app.models.auth.user import UserRole, UserStatus


@pytest.fixture(autouse=True)
def uow():
    """Replace the database the dependencies read the user's status from."""
    uow = AsyncMock()
    uow.user_repo.get_status = AsyncMock(return_value=UserStatus.ACTIVE)
    with patch("app.core.dependencies.UnitOfWork") as unit_of_work:
        unit_of_work.return_value.__aenter__.return_value = uow
        yield uow


def _claims(role: UserRole, *, valid_signature: bool = True):
    """Patch token decoding to yield the given role, or to fail verification."""
    payload = {"sub": str(uuid4()), "role": role} if valid_signature else None
    unverified = patch(
        "app.core.dependencies.jwt.get_unverified_claims",
        return_value={"role": role},
    )
    decoded = patch("app.core.dependencies.decode_token", return_value=payload)
    return payload, unverified, decoded


@pytest.mark.parametrize(
    ("dependency", "role"),
    [
        (require_admin, UserRole.ADMIN),
        (require_admin_or_analyst, UserRole.ANALYST),
        (require_any, UserRole.FIELD_WORKER),
    ],
)
async def test_valid_token_returns_the_actor(dependency, role):
    payload, unverified, decoded = _claims(role)
    with unverified, decoded:
        actor = await dependency(token="anytoken")
    assert str(actor.user_id) == payload["sub"]
    assert actor.role == role


@pytest.mark.parametrize(
    ("dependency", "role"),
    [
        (require_admin, UserRole.ADMIN),
        (require_admin_or_analyst, UserRole.ANALYST),
        (require_any, UserRole.FIELD_WORKER),
    ],
)
async def test_blocked_user_with_valid_token_raises_user_blocked(dependency, role, uow):
    uow.user_repo.get_status.return_value = UserStatus.BLOCKED
    _, unverified, decoded = _claims(role)
    with unverified, decoded:
        with pytest.raises(UserBlockedError):
            await dependency(token="anytoken")


@pytest.mark.parametrize(
    "dependency", [require_admin, require_admin_or_analyst, require_any]
)
async def test_invalid_signature_raises_401(dependency):
    _, unverified, decoded = _claims(UserRole.ADMIN, valid_signature=False)
    with unverified, decoded:
        with pytest.raises(UnauthorizedError):
            await dependency(token="anytoken")


@pytest.mark.parametrize("dependency", [require_admin, require_any])
async def test_malformed_token_raises_401(dependency):
    with patch(
        "app.core.dependencies.jwt.get_unverified_claims", side_effect=JWTError()
    ):
        with pytest.raises(UnauthorizedError):
            await dependency(token="notajwt")


@pytest.mark.parametrize("dependency", [require_admin, require_admin_or_analyst])
async def test_wrong_role_raises_403(dependency):
    _, unverified, decoded = _claims(UserRole.FIELD_WORKER)
    with unverified, decoded:
        with pytest.raises(ForbiddenError):
            await dependency(token="anytoken")
