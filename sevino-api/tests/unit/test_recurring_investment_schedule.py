"""Unit tests for the recurring-investment cadence math."""

from datetime import date

import pytest

from app.services.recurring_investment import compute_next_run_date


def test_weekly_advances_seven_days_preserving_weekday():
    # 2026-06-05 is a Friday.
    assert compute_next_run_date(date(2026, 6, 5), "weekly") == date(2026, 6, 12)


def test_biweekly_advances_fourteen_days():
    assert compute_next_run_date(date(2026, 6, 5), "biweekly") == date(2026, 6, 19)


def test_monthly_preserves_day_of_month():
    assert compute_next_run_date(date(2026, 6, 15), "monthly") == date(2026, 7, 15)


def test_monthly_clamps_to_short_month_end():
    # Jan 31 → Feb has no 31st, clamp to the 28th (2026 is not a leap year).
    assert compute_next_run_date(date(2026, 1, 31), "monthly") == date(2026, 2, 28)


def test_monthly_rolls_over_year_boundary():
    assert compute_next_run_date(date(2026, 12, 15), "monthly") == date(2027, 1, 15)


def test_daily_advances_one_day_midweek():
    # Mon → Tue.
    assert compute_next_run_date(date(2026, 6, 8), "daily") == date(2026, 6, 9)


def test_daily_skips_weekend():
    # Fri → Mon (Sat/Sun are not trading days).
    assert compute_next_run_date(date(2026, 6, 5), "daily") == date(2026, 6, 8)


def test_unsupported_frequency_raises():
    with pytest.raises(ValueError):
        compute_next_run_date(date(2026, 6, 5), "yearly")
