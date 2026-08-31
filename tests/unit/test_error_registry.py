"""Pins the public error catalog. Changing a slug or status here is an API
change: update EXPECTED deliberately and coordinate with client teams."""

from app.exceptions.domain_exceptions import ERROR_REGISTRY

EXPECTED: dict[str, int] = {
    "account-pending-validation": 403,
    "admin/invite-already-pending": 409,
    "auth/invalid-recovery-token": 401,
    "auth/invalid-refresh-token": 401,
    "auth/invalid-verification-token": 401,
    "auth/missing-token": 401,
    "auth/recovery-token-expired": 401,
    "auth/recovery-token-used": 401,
    "auth/verification-token-expired": 401,
    "auth/verification-token-used": 401,
    "email-delivery-failed": 502,
    "establishment-access-denied": 403,
    "establishment-already-exists": 409,
    "establishment-not-found": 404,
    "establishment-request-already-reviewed": 409,
    "establishment-request-not-found": 404,
    "field-worker-is-not-pending": 400,
    "filter-not-applicable": 400,
    "invalid-age-range": 400,
    "invalid-credentials": 401,
    "invalid-date-range": 400,
    "invalid-survey-payload": 400,
    "invalid-survey-response": 400,
    "invalid-survey-structure": 400,
    "invalid-user-role": 400,
    "no-fields-to-update": 400,
    "not-resource-owner": 403,
    "password-not-found": 404,
    "role-not-allowed": 403,
    "subject-already-exists": 409,
    "subject-not-found": 404,
    "survey-already-exists": 409,
    "survey-locked": 409,
    "survey-not-available": 403,
    "survey-not-found": 404,
    "survey-response-already-exists": 409,
    "survey-response-not-found": 404,
    "unauthorized": 401,
    "user-already-exists": 409,
    "user-establishment-not-approved": 409,
    "user-establishment-not-found": 404,
    "user-is-not-a-field-worker": 400,
    "user-is-not-active": 400,
    "user-is-not-pending": 400,
    "user-not-found": 404,
}


def test_error_catalog_matches_snapshot():
    actual = {slug: cls.status for slug, cls in ERROR_REGISTRY.items()}
    assert dict(sorted(actual.items())) == dict(sorted(EXPECTED.items()))
