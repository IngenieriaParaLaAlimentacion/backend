from datetime import date

import pytest

from app.utils.dates import completed_months_between


@pytest.mark.parametrize(
    "start,end,expected",
    [
        (date(2010, 3, 15), date(2020, 3, 15), 120),
        (date(2010, 3, 20), date(2020, 3, 15), 119),
        (date(2010, 3, 10), date(2020, 3, 15), 120),
        (date(2024, 1, 1), date(2024, 1, 1), 0),
        (date(2024, 6, 1), date(2024, 1, 1), 0),
    ],
    ids=["day-reached", "day-not-reached", "day-passed", "same-day", "future-start"],
)
def test_completed_months_between(start, end, expected):
    assert completed_months_between(start, end) == expected
