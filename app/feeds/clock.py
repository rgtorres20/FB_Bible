"""The one place a timestamp becomes text.

CLAUDE.md: every timestamp renders in the user's Houston timezone. That
rule was being kept by six modules each declaring their own
`CENTRAL = ZoneInfo("America/Chicago")`, and one formatter living in a
page module that a data unit then had to reach upward into
(`tests/test_boundaries.py`, breach list, Aug 21).

Both are the same problem: a kernel fact with no kernel to live in.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

# The blueprint is explicit that every timestamp renders in the user's zone.
CENTRAL = ZoneInfo("America/Chicago")
DOT = "·"


def format_time(iso: str | None) -> str:
    """'2026-08-14T16:00:00+00:00' -> 'Fri Aug 14 · 11:00 AM' (Central).

    Built by hand rather than with %-d/%-I, which are not portable to Windows.
    """
    if not iso:
        return ""
    try:
        stamp = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    if stamp.tzinfo is None:
        # Naive input means UTC -- the same convention rss.parse_date
        # states. astimezone() on a naive stamp would read it as the
        # HOST's zone, so the same feed would render differently on a
        # laptop and on Vercel while both claim Central.
        stamp = stamp.replace(tzinfo=UTC)
    stamp = stamp.astimezone(CENTRAL)
    hour = stamp.hour % 12 or 12
    meridiem = "AM" if stamp.hour < 12 else "PM"
    return f"{stamp:%a} {stamp:%b} {stamp.day} {DOT} {hour}:{stamp:%M} {meridiem}"


def today():
    """Houston's date. `date.today()` is the HOST's date -- UTC on Vercel
    -- so between 7pm and midnight Central every "N days old" figure read
    one day older than the owner's calendar said.
    """
    return datetime.now(CENTRAL).date()
