import asyncio

from app.exceptions.domain_exceptions import (
    EstablishmentNotFoundError,
    ForbiddenError,
    PasswordNotFoundError,
    SubjectAlreadyExistsError,
    UnauthorizedError,
    UserAlreadyExistsError,
    UserEstablishmentNotFoundError,
    UserNotFoundError,
)
from app.exceptions.exception_handlers import (
    _build_error_response,
    forbidden_handler,
    not_found_handler,
    subject_already_exists_handler,
    unauthorized_handler,
    user_already_exists_handler,
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


def test_user_already_exists_handler():
    request = DummyRequest("/register")
    response = asyncio.run(
        user_already_exists_handler(request, UserAlreadyExistsError("taken@email.com"))
    )
    assert response.status_code == 409
    assert b"taken@email.com" in response.body
    assert b"User already exists" in response.body


def test_not_found_handler_user():
    request = DummyRequest("/users/123")
    response = asyncio.run(not_found_handler(request, UserNotFoundError("123")))
    assert response.status_code == 404
    assert b"123" in response.body
    assert b"User not found" in response.body


def test_not_found_handler_password():
    request = DummyRequest("/login")
    response = asyncio.run(not_found_handler(request, PasswordNotFoundError("456")))
    assert response.status_code == 404
    assert b"456" in response.body
    assert b"Password not found" in response.body


def test_not_found_handler_establishment():
    request = DummyRequest("/establishments/789")
    response = asyncio.run(
        not_found_handler(request, EstablishmentNotFoundError("789"))
    )
    assert response.status_code == 404
    assert b"789" in response.body
    assert b"Establishment not found" in response.body


def test_not_found_handler_user_establishment():
    request = DummyRequest("/admin/managers/u1/approve")
    response = asyncio.run(
        not_found_handler(
            request, UserEstablishmentNotFoundError("estab-id", "user-id")
        )
    )
    assert response.status_code == 404
    assert b"estab-id" in response.body
    assert b"User establishment not found" in response.body


def test_unauthorized_handler():
    request = DummyRequest("/me")
    response = asyncio.run(unauthorized_handler(request, UnauthorizedError()))
    assert response.status_code == 401
    assert b"Unauthorized" in response.body


def test_forbidden_handler():
    request = DummyRequest("/admin/users")
    response = asyncio.run(forbidden_handler(request, ForbiddenError()))
    assert response.status_code == 403
    assert b"Forbidden" in response.body


def test_subject_already_exists_handler():
    request = DummyRequest("/upload-subject")
    response = asyncio.run(
        subject_already_exists_handler(request, SubjectAlreadyExistsError(20000000))
    )
    assert response.status_code == 409
    assert b"20000000" in response.body
    assert b"Subject already exists" in response.body
