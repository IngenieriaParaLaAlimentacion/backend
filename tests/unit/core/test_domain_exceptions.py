import pytest

from app.exceptions.domain_exceptions import (
    NotFoundError,
    UserNotFoundError,
)


def test_subclass_without_own_error_type_is_rejected():
    with pytest.raises(TypeError, match="must declare `error_type`"):

        class Bad(NotFoundError):
            pass


def test_malformed_slug_is_rejected():
    with pytest.raises(TypeError, match="malformed"):

        class Bad(NotFoundError):
            error_type = "Not_A_Slug"


def test_duplicate_slug_is_rejected():
    with pytest.raises(TypeError, match="Duplicate error_type"):

        class Bad(NotFoundError):
            error_type = "user-not-found"


def test_inherited_error_type_is_rejected():
    with pytest.raises(TypeError, match="must declare `error_type`"):

        class Bad(UserNotFoundError):
            pass
