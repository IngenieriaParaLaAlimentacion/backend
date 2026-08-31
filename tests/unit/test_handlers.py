import asyncio
import json

from app.exceptions.domain_exceptions import (
    RoleNotAllowedError,
    SubjectAlreadyExistsError,
    SubjectNotFoundError,
    SurveyLockedError,
    UnauthorizedError,
    UserAlreadyExistsError,
)
from app.exceptions.exception_handlers import domain_error_handler


class DummyRequest:
    def __init__(self, path):
        self.url = type("url", (), {"path": path})


def _handle(path, exc):
    return asyncio.run(domain_error_handler(DummyRequest(path), exc))


def test_domain_error_handler_builds_canonical_envelope():
    response = _handle("/foo", UserAlreadyExistsError("foo@bar.com"))

    assert response.status_code == 409
    assert response.media_type == "application/problem+json"
    body = json.loads(response.body)
    assert body == {
        "type": "/errors/user-already-exists",
        "title": "User already exists",
        "status": 409,
        "detail": "A user with email foo@bar.com already exists.",
        "instance": "/foo",
    }


def test_not_found_error():
    response = _handle("/subjects/123", SubjectNotFoundError("123"))

    assert response.status_code == 404
    body = json.loads(response.body)
    assert body["type"] == "/errors/subject-not-found"
    assert body["title"] == "Subject not found"
    assert "123" in body["detail"]


def test_already_exists_error():
    response = _handle("/register", UserAlreadyExistsError("taken@email.com"))

    assert response.status_code == 409
    assert b"taken@email.com" in response.body
    assert b"User already exists" in response.body


def test_unauthorized_error():
    response = _handle("/me", UnauthorizedError())

    assert response.status_code == 401
    assert json.loads(response.body)["type"] == "/errors/unauthorized"


def test_forbidden_error():
    response = _handle("/admin/users", RoleNotAllowedError())

    assert response.status_code == 403
    assert json.loads(response.body)["type"] == "/errors/role-not-allowed"


def test_reason_is_rendered_as_a_top_level_member():
    response = _handle(
        "/surveys/1", SurveyLockedError("has_responses", "Cannot delete.")
    )

    body = json.loads(response.body)
    assert body["type"] == "/errors/survey-locked"
    assert body["reason"] == "has_responses"


def test_reason_is_absent_when_the_error_declares_none():
    response = _handle("/subjects/123", SubjectNotFoundError("123"))

    assert "reason" not in json.loads(response.body)


def test_extensions_are_merged_into_the_body():
    response = _handle("/subjects", SubjectAlreadyExistsError(123, {"id": "x"}))

    assert json.loads(response.body)["canonical_subject"] == {"id": "x"}


def test_extensions_cannot_overwrite_canonical_members():
    exc = SubjectAlreadyExistsError(123, canonical={"id": "x"})
    exc.extensions["type"] = "/errors/HIJACKED"
    exc.extensions["status"] = 999

    response = _handle("/p", exc)
    body = json.loads(response.body)

    assert body["type"] == "/errors/subject-already-exists"
    assert body["status"] == 409
    assert body["canonical_subject"] == {"id": "x"}
