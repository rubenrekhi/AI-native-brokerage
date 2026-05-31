from datetime import datetime, timezone

from app.ai.utils.time_context import build_time_context

# 2026-05-30 is a Saturday; May is EDT (UTC-4). 2026-01-15 is a Thursday in
# EST (UTC-5). Weekday/label correctness is the whole point of these cases.


def test_heading_present_and_time_rendered_in_et():
    now = datetime(2026, 5, 30, 19, 45, tzinfo=timezone.utc)
    out = build_time_context(now, None)
    assert out.startswith("## Current date, time, and market status")
    assert "Saturday, May 30, 2026 at 3:45 PM EDT" in out
    assert "US Eastern Time" in out


def test_no_market_line_when_status_unavailable():
    now = datetime(2026, 5, 30, 19, 45, tzinfo=timezone.utc)
    out = build_time_context(now, None)
    assert "stock market is currently" not in out


def test_winter_instant_labels_est():
    now = datetime(2026, 1, 15, 19, 45, tzinfo=timezone.utc)
    out = build_time_context(now, None)
    assert "Thursday, January 15, 2026 at 2:45 PM EST" in out


def test_naive_now_is_treated_as_utc():
    naive = datetime(2026, 5, 30, 19, 45)
    aware = datetime(2026, 5, 30, 19, 45, tzinfo=timezone.utc)
    assert build_time_context(naive, None) == build_time_context(aware, None)


def test_market_open_includes_next_close():
    now = datetime(2026, 5, 29, 17, 0, tzinfo=timezone.utc)
    status = {
        "is_open": True,
        "next_open": "",
        "next_close": "2026-05-29T20:00:00Z",
    }
    out = build_time_context(now, status)
    assert "The US stock market is currently open." in out
    assert "It next closes Friday, May 29, 2026 at 4:00 PM EDT." in out


def test_market_closed_includes_next_open_with_offset_timestamp():
    now = datetime(2026, 5, 30, 18, 0, tzinfo=timezone.utc)
    status = {
        "is_open": False,
        "next_open": "2026-06-01T09:30:00-04:00",
        "next_close": "",
    }
    out = build_time_context(now, status)
    assert "The US stock market is currently closed." in out
    assert "It next opens Monday, June 1, 2026 at 9:30 AM EDT." in out


def test_open_without_parseable_next_close_omits_clause():
    now = datetime(2026, 5, 29, 17, 0, tzinfo=timezone.utc)
    out = build_time_context(now, {"is_open": True, "next_close": "garbage"})
    assert "currently open." in out
    assert "next closes" not in out


def test_missing_is_open_key_treated_as_closed():
    now = datetime(2026, 5, 30, 18, 0, tzinfo=timezone.utc)
    out = build_time_context(now, {})
    assert "The US stock market is currently closed." in out


# ---- client timezone ----


def test_client_timezone_renders_local_beside_eastern():
    # 19:45 UTC in May → 12:45 PM PDT (UTC-7) and 3:45 PM EDT (UTC-4).
    now = datetime(2026, 5, 30, 19, 45, tzinfo=timezone.utc)
    out = build_time_context(now, None, client_timezone="America/Los_Angeles")
    assert "Saturday, May 30, 2026 at 12:45 PM PDT (the user's local time)" in out
    assert "In US Eastern Time — the timezone US markets operate on — it is " in out
    assert "Saturday, May 30, 2026 at 3:45 PM EDT" in out


def test_client_timezone_crossing_date_line_renders_local_date():
    # 19:45 UTC → 04:45 the next day in Tokyo (UTC+9, no DST). The local date
    # must roll to Sunday while Eastern stays Saturday.
    now = datetime(2026, 5, 30, 19, 45, tzinfo=timezone.utc)
    out = build_time_context(now, None, client_timezone="Asia/Tokyo")
    assert "Sunday, May 31, 2026 at 4:45 AM JST (the user's local time)" in out
    assert "Saturday, May 30, 2026 at 3:45 PM EDT" in out


def test_client_timezone_equal_to_eastern_collapses_to_single_line():
    now = datetime(2026, 5, 30, 19, 45, tzinfo=timezone.utc)
    out = build_time_context(now, None, client_timezone="America/New_York")
    assert "the user's local time" not in out
    assert "Saturday, May 30, 2026 at 3:45 PM EDT (US Eastern Time" in out


def test_client_timezone_sharing_eastern_offset_collapses():
    # America/Detroit observes Eastern — same offset as New York, so the
    # local clock is identical and the duplicate line is dropped.
    now = datetime(2026, 5, 30, 19, 45, tzinfo=timezone.utc)
    out = build_time_context(now, None, client_timezone="America/Detroit")
    assert "the user's local time" not in out
    assert "3:45 PM EDT (US Eastern Time" in out


def test_unknown_client_timezone_falls_back_to_eastern_only():
    now = datetime(2026, 5, 30, 19, 45, tzinfo=timezone.utc)
    out = build_time_context(now, None, client_timezone="Mars/Olympus_Mons")
    assert "the user's local time" not in out
    assert "Saturday, May 30, 2026 at 3:45 PM EDT (US Eastern Time" in out


def test_path_traversal_client_timezone_falls_back_to_eastern_only():
    # ZoneInfo raises ValueError (not ZoneInfoNotFoundError) for keys with
    # ".." or leading "/"; both must degrade rather than raise.
    now = datetime(2026, 5, 30, 19, 45, tzinfo=timezone.utc)
    for bogus in ("../../etc/passwd", "/etc/localtime", ""):
        out = build_time_context(now, None, client_timezone=bogus)
        assert "3:45 PM EDT (US Eastern Time" in out


def test_client_timezone_keeps_market_status_in_eastern():
    now = datetime(2026, 5, 29, 17, 0, tzinfo=timezone.utc)
    status = {"is_open": True, "next_close": "2026-05-29T20:00:00Z"}
    out = build_time_context(
        now, status, client_timezone="America/Los_Angeles"
    )
    assert "(the user's local time)" in out
    assert "The US stock market is currently open." in out
    assert "It next closes Friday, May 29, 2026 at 4:00 PM EDT." in out
