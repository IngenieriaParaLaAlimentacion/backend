import asyncio

from app.exceptions.domain_exceptions import (
    ForbiddenError,
    SubjectNotFoundError,
    UnauthorizedError,
    UserAlreadyExistsError,
)
from app.exceptions.exception_handlers import (
    _build_error_response,
    already_exists_handler,
    forbidden_handler,
    not_found_handler,
    unauthorized_handler,
)


class DummyRequest:
    def __init__(self, path):
        self.url = type("url", (), {"path": path})


def test_build_error_response():
    error = UserAlreadyExistsError("foo@bar.com")
    request = DummyRequest("/foo")
    response = _build_error_response(error, request, 409)
    assert response.status_code == 409
    assert response.media_type == "application/problem+json"
    assert b"foo@bar.com" in response.body
    assert b"User already exists" in response.body
    assert b"/foo" in response.body


def test_not_found_handler():
    request = DummyRequest("/subjects/123")
    response = asyncio.run(not_found_handler(request, SubjectNotFoundError("123")))
    assert response.status_code == 404
    assert b"123" in response.body


def test_already_exists_handler():
    request = DummyRequest("/register")
    response = asyncio.run(
        already_exists_handler(request, UserAlreadyExistsError("taken@email.com"))
    )
    assert response.status_code == 409
    assert b"taken@email.com" in response.body


def test_unauthorized_handler():
    request = DummyRequest("/me")
    response = asyncio.run(unauthorized_handler(request, UnauthorizedError()))
    assert response.status_code == 401


def test_forbidden_handler():
    request = DummyRequest("/admin/users")
    response = asyncio.run(forbidden_handler(request, ForbiddenError()))
    assert response.status_code == 403
