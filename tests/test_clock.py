"""The kernel that turns an instant into the owner's calendar.

Both functions here are Houston-or-nothing, and both have a failure mode
that only shows up somewhere other than the machine the test was written
on: `format_time` reading a naive stamp as the *host's* zone, and
`today()` reading the host's date. On a laptop in Central both are
invisible; on Vercel, which runs UTC, they are wrong for five hours every
evening. So the zone is asserted against a fixed instant rather than
against whatever the runner happens to be set to.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.feeds import clock

# 9:30pm Central on Aug 22 -- the same instant is already Aug 23 in UTC.
EVENING = datetime(2026, 8, 23, 2, 30, tzinfo=UTC)


class _Frozen(datetime):
    """A clock stuck at EVENING, honouring whatever zone it is asked for."""

    @classmethod
    def now(cls, tz=None):
        return EVENING.astimezone(tz) if tz else EVENING.replace(tzinfo=None)


def test_a_naive_stamp_is_read_as_utc_not_as_the_host_s_zone():
    """`rss.parse_date` hands on naive ISO for publishers that omit the
    offset. astimezone() on a naive stamp assumes the host's zone, so the
    same feed item rendered one hour on a Central laptop and six on
    Vercel while both pages claimed Central. The two spellings of the
    same instant have to render identically."""
    assert clock.format_time("2026-08-14T16:00:00") == clock.format_time(
        "2026-08-14T16:00:00+00:00"
    )
    assert clock.format_time("2026-08-14T16:00:00") == "Fri Aug 14 · 11:00 AM"


def test_a_stamp_that_already_carries_a_zone_is_converted_not_relabelled():
    """An offset in the string is a fact about the instant; treating it
    as Central would move the story by the difference."""
    # 11:00 AM Central expressed from the other coast.
    assert clock.format_time("2026-08-14T09:00:00-07:00") == "Fri Aug 14 · 11:00 AM"


def test_today_is_houston_s_date_and_not_the_hosts(monkeypatch):
    """Between 7pm and midnight Central the host's UTC date is already
    tomorrow, so every "N days old" figure on the app -- rank-list ages,
    as-of stamps -- read a day older than the owner's calendar said."""
    monkeypatch.setattr(clock, "datetime", _Frozen)
    assert clock.today() == date(2026, 8, 22)
    # The bug, stated: the host would have said the 23rd.
    assert _Frozen.now(UTC).date() == date(2026, 8, 23)


def test_today_returns_a_date_rather_than_a_stamp(monkeypatch):
    """Callers compare it with `date.fromisoformat` values from stored
    lists (`app/routes/userdata.py`); a datetime would compare unequal to
    every one of them."""
    monkeypatch.setattr(clock, "datetime", _Frozen)
    value = clock.today()
    assert isinstance(value, date) and not isinstance(value, datetime)
    assert value.isoformat() == "2026-08-22"
