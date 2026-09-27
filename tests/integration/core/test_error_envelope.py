"""Every error branch of the API must leave in the same problem+json envelope.

One test per producer: domain 4xx, validation 422, route 404, method 405 and
unhandled 500. Each asserts the media type and that ``detail`` is a string --
the shape the backoffice reported as ``[object Object]``.
"""

from app.core.dependencies import get_auth_service
from tests.integration.urls import LOGIN_URL


def _assert_problem(response, *, status_code: int, error_type: str) -> dict:
    """Assert the canonical envelope and return the parsed body."""
    assert response.status_code == status_code
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == f"/errors/{error_type}"
    assert isinstance(body["detail"], str)
    assert isinstance(body["title"], str)
    assert body["status"] == status_code
    assert body["instance"]
    return body


async def test_domain_error_is_problem_json(client):
    response = await client.post(
        LOGIN_URL,
        json={
            "email": "nobody@test.com",
            "password": "whatever",
            "device_id": "11111111-1111-1111-1111-111111111111",
        },
    )

    _assert_problem(response, status_code=401, error_type="invalid-credentials")


async def test_validation_error_is_problem_json_with_string_detail(client):
    response = await client.post(LOGIN_URL, json={})

    body = _assert_problem(response, status_code=422, error_type="validation-failed")
    assert set(body) == {"type", "title", "status", "detail", "instance"}


async def test_validation_error_does_not_echo_submitted_values(client):
    response = await client.post(
        LOGIN_URL,
        json={
            "email": "a@b.com",
            "password": "sup3rs3cr3t",
            "device_id": "not-a-uuid",
        },
    )

    assert response.status_code == 422
    assert "sup3rs3cr3t" not in response.text


async def test_query_validation_error_is_problem_json(client, admin_headers):
    response = await client.get("/api/v1/subjects?page=0", headers=admin_headers)

    _assert_problem(response, status_code=422, error_type="validation-failed")


async def test_unrouted_path_is_problem_json(client):
    response = await client.get("/api/v1/definitely-not-a-route")

    _assert_problem(response, status_code=404, error_type="not-found")


async def test_method_not_allowed_is_problem_json_and_keeps_allow_header(client):
    response = await client.delete(LOGIN_URL)

    _assert_problem(response, status_code=405, error_type="method-not-allowed")
    assert "POST" in response.headers["allow"]


async def test_unhandled_error_is_problem_json(raw_client, app):
    def _boom():
        raise RuntimeError("kaboom")

    app.dependency_overrides[get_auth_service] = _boom
    try:
        response = await raw_client.post(
            LOGIN_URL,
            json={
                "email": "a@b.com",
                "password": "whatever",
                "device_id": "11111111-1111-1111-1111-111111111111",
            },
        )
    finally:
        app.dependency_overrides.pop(get_auth_service, None)

    body = _assert_problem(response, status_code=500, error_type="internal-error")
    assert "kaboom" not in response.text
    assert body["detail"] == "An unexpected error occurred."


def _dbapi_error(sqlstate: str):
    """A DBAPIError shaped like the one asyncpg's wrapper raises."""
    from sqlalchemy.exc import DBAPIError

    class _DriverError(Exception):
        pass

    orig = _DriverError("database said no")
    orig.sqlstate = sqlstate
    return DBAPIError("UPDATE food_stock SET ...", None, orig)


async def _post_login_with_failing_dependency(raw_client, app, error: Exception):
    """Drive a request whose dependency blows up with ``error``."""

    def _boom():
        raise error

    app.dependency_overrides[get_auth_service] = _boom
    try:
        return await raw_client.post(
            LOGIN_URL,
            json={
                "email": "a@b.com",
                "password": "whatever",
                "device_id": "11111111-1111-1111-1111-111111111111",
            },
        )
    finally:
        app.dependency_overrides.pop(get_auth_service, None)


async def test_deadlock_is_a_retryable_503(raw_client, app):
    """40P01 rolled everything back, so the client should just try again."""
    response = await _post_login_with_failing_dependency(
        raw_client, app, _dbapi_error("40P01")
    )

    _assert_problem(response, status_code=503, error_type="concurrent-update")
    assert response.headers["retry-after"] == "1"


async def test_serialization_failure_is_a_retryable_503(raw_client, app):
    response = await _post_login_with_failing_dependency(
        raw_client, app, _dbapi_error("40001")
    )

    _assert_problem(response, status_code=503, error_type="concurrent-update")


async def test_other_database_errors_stay_500(raw_client, app):
    """Only class 40 is retryable: everything else must not invite a replay."""
    response = await _post_login_with_failing_dependency(
        raw_client, app, _dbapi_error("23505")
    )

    _assert_problem(response, status_code=500, error_type="internal-error")
    assert "retry-after" not in response.headers


async def test_missing_and_invalid_token_share_one_envelope(client):
    missing = await client.get("/api/v1/users/me")
    invalid = await client.get(
        "/api/v1/users/me", headers={"Authorization": "Bearer nonsense"}
    )

    for response in (missing, invalid):
        assert response.status_code == 401
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.headers["www-authenticate"] == "Bearer"
        assert isinstance(response.json()["detail"], str)

    assert missing.json()["type"] == "/errors/auth/missing-token"
    assert invalid.json()["type"] == "/errors/unauthorized"


async def test_non_bearer_scheme_is_a_missing_token_not_a_crash(client):
    response = await client.get(
        "/api/v1/users/me", headers={"Authorization": "Basic dXNlcjpwYXNz"}
    )

    _assert_problem(response, status_code=401, error_type="auth/missing-token")
