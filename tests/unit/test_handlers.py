import asyncio

from app.exceptions.domain_exceptions import (
    EstablishmentNotFoundError,
    PasswordNotFoundError,
    UnauthorizedError,
    UserAlreadyExistsError,
    UserNotFoundError,
)
from app.exceptions.exception_handlers import (
    _build_error_response,
    establishment_not_found_handler,
    password_not_found_handler,
    unauthorized_handler,
    user_already_exists_handler,
    user_not_found_handler,
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


def test_user_not_found_handler():
    request = DummyRequest("/users/123")
    response = asyncio.run(user_not_found_handler(request, UserNotFoundError("123")))
    assert response.status_code == 404
    assert b"123" in response.body
    assert b"User not found" in response.body


def test_password_not_found_handler():
    request = DummyRequest("/login")
    response = asyncio.run(
        password_not_found_handler(request, PasswordNotFoundError("456"))
    )
    assert response.status_code == 404
    assert b"456" in response.body
    assert b"Password not found" in response.body


def test_unauthorized_handler():
    request = DummyRequest("/me")
    response = asyncio.run(unauthorized_handler(request, UnauthorizedError()))
    assert response.status_code == 401
    assert b"Unauthorized" in response.body


def test_establishment_not_found_handler():
    request = DummyRequest("/establishments/789")
    response = asyncio.run(
        establishment_not_found_handler(request, EstablishmentNotFoundError("789"))
    )
    assert response.status_code == 404
    assert b"789" in response.body
    assert b"Establishment not found" in response.body
