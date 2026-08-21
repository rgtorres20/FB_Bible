"""The one place a timestamp becomes text.

CLAUDE.md: every timestamp renders in the user's Houston timezone. That
rule was being kept by six modules each declaring their own
`CENTRAL = ZoneInfo("America/Chicago")`, and one formatter living in a
page module that a data unit then had to reach upward into
(`tests/test_boundaries.py`, breach list, Aug 21).

Both are the same problem: a kernel fact with no kernel to live in.
"""

from __future__ import annotations

from datetime import datetime
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
        stamp = datetime.fromisoformat(iso).astimezone(CENTRAL)
    except ValueError:
        return ""
    hour = stamp.hour % 12 or 12
    meridiem = "AM" if stamp.hour < 12 else "PM"
    return f"{stamp:%a} {stamp:%b} {stamp.day} {DOT} {hour}:{stamp:%M} {meridiem}"
