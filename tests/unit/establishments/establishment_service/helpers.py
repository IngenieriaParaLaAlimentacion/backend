from app.schemas.establishments.establishment_schema import (
    EstablishmentApprovalRequest,
    EstablishmentRequest,
)

_REQUEST_DEFAULTS = {
    "name": "Centro A",
    "formatted_address": "Calle 1",
    "latitude": -34.6,
    "longitude": -58.4,
    "place_id": "place-test-001",
    "city": "Buenos Aires",
    "province": "Buenos Aires",
}


def _make_request(**overrides) -> EstablishmentRequest:
    return EstablishmentRequest(**{**_REQUEST_DEFAULTS, **overrides})


def _make_approval(**overrides) -> EstablishmentApprovalRequest:
    return EstablishmentApprovalRequest(**{**_REQUEST_DEFAULTS, **overrides})
