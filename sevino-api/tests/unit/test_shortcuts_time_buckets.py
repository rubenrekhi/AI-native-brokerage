"""Unit tests for shortcut time-bucket mapping (US Eastern, DST-aware)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.shortcuts.time_buckets import ET, TimeBucket, current_bucket


def _et(hour: int, minute: int = 0) -> datetime:
    # A summer weekday well clear of any DST transition; the bucket only
    # depends on the ET wall clock, which astimezone preserves.
    return datetime(2026, 6, 15, hour, minute, tzinfo=ET)


@pytest.mark.parametrize(
    "hour,minute,expected",
    [
        (3, 59, TimeBucket.NIGHT),
        (4, 0, TimeBucket.MORNING),
        (9, 29, TimeBucket.MORNING),
        (9, 30, TimeBucket.MARKET_HOURS),
        (15, 59, TimeBucket.MARKET_HOURS),
        (16, 0, TimeBucket.AFTER_MARKET),
        (19, 59, TimeBucket.AFTER_MARKET),
        (20, 0, TimeBucket.NIGHT),
        (0, 0, TimeBucket.NIGHT),
        (23, 59, TimeBucket.NIGHT),
    ],
)
def test_bucket_boundaries(hour, minute, expected):
    assert current_bucket(_et(hour, minute)) == expected


def test_same_utc_instant_differs_across_dst():
    # 14:00 UTC is 09:00 EST in winter (MORNING) but 10:00 EDT in summer
    # (MARKET_HOURS) — proves the mapping tracks the offset, not a fixed one.
    winter = datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc)
    summer = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)
    assert current_bucket(winter) == TimeBucket.MORNING
    assert current_bucket(summer) == TimeBucket.MARKET_HOURS


def test_spring_forward_transition():
    # 2026-03-08: clocks jump 02:00 EST -> 03:00 EDT at 07:00 UTC.
    instant = datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc)
    et = instant.astimezone(ET)
    assert et.hour == 3
    assert et.utcoffset() == timedelta(hours=-4)
    assert current_bucket(instant) == TimeBucket.NIGHT


def test_fall_back_transition():
    # 2026-11-01: clocks fall 02:00 EDT -> 01:00 EST at 06:00 UTC, so the
    # 01:30 ET hour occurs twice. Both passes land in NIGHT.
    first_pass = datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)
    second_pass = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)
    assert first_pass.astimezone(ET).utcoffset() == timedelta(hours=-4)
    assert second_pass.astimezone(ET).utcoffset() == timedelta(hours=-5)
    assert current_bucket(first_pass) == TimeBucket.NIGHT
    assert current_bucket(second_pass) == TimeBucket.NIGHT
