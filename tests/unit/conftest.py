import uuid
from unittest.mock import MagicMock

import pytest

from app.models import UserRole, UserStatus


@pytest.fixture
def make_establishment():
    """Return a factory that builds a mock Establishment with a random id."""

    def _make(name: str = "Centro A", address: str = "Calle 1"):
        e = MagicMock()
        e.id = uuid.uuid4()
        e.name = name
        e.address = address
        return e

    return _make


@pytest.fixture
def make_user():
    """Return a factory that builds a mock User with ESTABLISHMENT_MANAGER role."""

    def _make():
        u = MagicMock()
        u.id = uuid.uuid4()
        u.role = UserRole.ESTABLISHMENT_MANAGER
        u.status = UserStatus.PENDING_VALIDATION
        return u

    return _make
