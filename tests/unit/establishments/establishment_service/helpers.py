from app.schemas.establishments.establishment_schema import (
    EstablishmentRequest,
)


def _make_request(**overrides) -> EstablishmentRequest:
    defaults = {
        "name": "Centro A",
        "formatted_address": "Calle 1",
        "latitude": -34.6,
        "longitude": -58.4,
        "place_id": "place-test-001",
        "city": "Buenos Aires",
        "province": "Buenos Aires",
    }
    defaults.update(overrides)
    return EstablishmentRequest(**defaults)
