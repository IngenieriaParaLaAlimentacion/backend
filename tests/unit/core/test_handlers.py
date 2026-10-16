import asyncio
import json

from app.exceptions.domain_exceptions import (
    SubjectAlreadyExistsError,
    SurveyLockedError,
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


def test_the_envelope_carries_only_the_five_canonical_members():
    response = _handle("/surveys/1", SurveyLockedError("Cannot delete."))

    body = json.loads(response.body)
    assert body["type"] == "/errors/survey-locked"
    assert set(body) == {"type", "title", "status", "detail", "instance"}


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
