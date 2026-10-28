"""Subject-export age and elapsed-time policy at explicit reference instants."""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.services.exporters.csv.subject_time import (
    format_current_age,
    format_measurement_elapsed,
)

REFERENCE = datetime(2026, 10, 28, 15, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "birth_date,expected",
    [
        (date(2008, 4, 28), "18 a 6 m"),
        (date(2008, 4, 29), "18 a 5 m"),
        (date(2024, 10, 28), "2 a"),
        (date(2026, 7, 28), "3 m"),
        (date(2026, 10, 28), "0 m"),
        (date(2027, 1, 1), "0 m"),
        (None, "—"),
    ],
)
def test_current_age(birth_date, expected):
    assert format_current_age(birth_date, REFERENCE) == expected


@pytest.mark.parametrize(
    "birth_date,reference,expected",
    [
        (date(2026, 1, 31), datetime(2026, 2, 28, 15, tzinfo=timezone.utc), "0 m"),
        (date(2026, 1, 31), datetime(2026, 3, 1, 15, tzinfo=timezone.utc), "1 m"),
        (date(2024, 2, 29), datetime(2025, 2, 28, 15, tzinfo=timezone.utc), "11 m"),
        (date(2024, 2, 29), datetime(2025, 3, 1, 15, tzinfo=timezone.utc), "1 a"),
        (
            date(2008, 4, 28),
            datetime(2026, 10, 29, 1, 30, tzinfo=timezone.utc),
            "18 a 6 m",
        ),
        (
            date(2008, 4, 28),
            datetime(2026, 10, 28, 2, 59, tzinfo=timezone.utc),
            "18 a 5 m",
        ),
    ],
)
def test_current_age_uses_completed_argentina_calendar_months(
    birth_date, reference, expected
):
    assert format_current_age(birth_date, reference) == expected


@pytest.mark.parametrize(
    "measured_at,expected",
    [
        (None, "—"),
        (REFERENCE + timedelta(seconds=1), "—"),
        (REFERENCE + timedelta(days=1), "—"),
        (REFERENCE, "hoy"),
        (datetime(2026, 10, 28, 3, tzinfo=timezone.utc), "hoy"),
        (datetime(2026, 10, 28, 1, 30, tzinfo=timezone.utc), "hace 1 día"),
        (datetime(2026, 10, 26, 15, tzinfo=timezone.utc), "hace 2 días"),
        (datetime(2026, 9, 29, 15, tzinfo=timezone.utc), "hace 29 días"),
        (datetime(2026, 9, 28, 15, tzinfo=timezone.utc), "hace 1 mes"),
        (datetime(2026, 7, 28, 15, tzinfo=timezone.utc), "hace 3 meses"),
        (datetime(2025, 11, 28, 15, tzinfo=timezone.utc), "hace 11 meses"),
        (datetime(2025, 10, 28, 15, tzinfo=timezone.utc), "hace 1 año"),
        (datetime(2024, 10, 28, 15, tzinfo=timezone.utc), "hace 2 años"),
        (datetime(2026, 10, 28, 1, 30), "hace 1 día"),
    ],
)
def test_measurement_elapsed(measured_at, expected):
    assert format_measurement_elapsed(measured_at, REFERENCE) == expected


@pytest.mark.parametrize(
    "measured_at,reference,expected",
    [
        (
            datetime(2026, 1, 31, 15, tzinfo=timezone.utc),
            datetime(2026, 2, 28, 15, tzinfo=timezone.utc),
            "hace 28 días",
        ),
        (
            datetime(2026, 1, 31, 15, tzinfo=timezone.utc),
            datetime(2026, 3, 1, 15, tzinfo=timezone.utc),
            "hace 1 mes",
        ),
        (
            datetime(2024, 2, 29, 15, tzinfo=timezone.utc),
            datetime(2025, 2, 28, 15, tzinfo=timezone.utc),
            "hace 11 meses",
        ),
        (
            datetime(2024, 2, 29, 15, tzinfo=timezone.utc),
            datetime(2025, 3, 1, 15, tzinfo=timezone.utc),
            "hace 1 año",
        ),
        (
            datetime(2026, 10, 28, 15, tzinfo=timezone.utc),
            datetime(2026, 10, 29, 1, 30, tzinfo=timezone.utc),
            "hoy",
        ),
    ],
)
def test_measurement_elapsed_uses_completed_calendar_months(
    measured_at, reference, expected
):
    assert format_measurement_elapsed(measured_at, reference) == expected
