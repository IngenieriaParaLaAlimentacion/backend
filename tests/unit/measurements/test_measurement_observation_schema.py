from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.measurements.measurement_schema import MeasurementRequest


def request(**overrides):
    return MeasurementRequest(
        subject_id=uuid4(),
        establishment_id=uuid4(),
        weight_kg=70,
        height_cm=175,
        measured_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        **overrides,
    )


def test_old_clients_can_omit_observation():
    assert request().observation is None


@pytest.mark.parametrize("value", [None, "", " \n\t "])
def test_empty_observations_are_null(value):
    assert request(observation=value).observation is None


def test_observation_keeps_multiline_text_and_trims_outer_whitespace():
    assert request(observation="  Repetir medición\nSin calzado.  ").observation == (
        "Repetir medición\nSin calzado."
    )


def test_observation_limit_applies_after_trimming():
    assert request(observation=" " + "a" * 500 + " ").observation == "a" * 500
    with pytest.raises(ValidationError):
        request(observation="a" * 501)


@pytest.mark.parametrize("value", [123, [], {}])
def test_observation_requires_text(value):
    with pytest.raises(ValidationError):
        request(observation=value)
