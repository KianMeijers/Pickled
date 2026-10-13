"""A Meal Plan's week (Saturday to Friday) uses the month most of its days fall in."""

from datetime import date

import pytest

from pickled.seasonal import month_of_week


@pytest.mark.parametrize(
    ("saturday", "month"),
    [
        (date(2026, 10, 24), 10),  # all seven days in October
        (date(2026, 10, 31), 11),  # 1 day in October, 6 in November
        (date(2026, 3, 28), 3),  # 4 days in March, 3 in April
        (date(2026, 11, 28), 12),  # 3 days in November, 4 in December
        (date(2026, 12, 26), 12),  # 6 days in December, 1 in the next January
        (date(2027, 1, 30), 2),  # 2 days in January, 5 in February
    ],
)
def test_a_week_uses_the_month_most_of_its_days_fall_in(saturday, month):
    assert month_of_week(saturday) == month
