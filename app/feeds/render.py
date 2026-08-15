"""Render polled items into the shape the app already reads.

The page fetches `data/feeds.json` at startup. Rather than edit a 257KB
generated design document -- which would fork it from the design project and
have to be re-merged forever -- the server serves that same path with live
data in the same shape. The app becomes live without knowing anything changed.

Field shapes were taken from the committed feeds.json, not invented:

    {"kind": "Wire", "handle": "Yahoo lineup wire", "trust": "Tier 1",
     "time": "Fri Aug 14 · 11:00 AM", "text": "...",
     "players": "Malik Willis · QB · MIA"}

Note `players` is a formatted string, not a list, and `time` is Central with
no zero padding. Both matter: the page renders them verbatim.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

# The blueprint is explicit that every timestamp renders in the user's zone.
CENTRAL = ZoneInfo("America/Chicago")
DOT = "·"

# The News tab is a reading surface, not an archive. The full set stays at
# /api/feeds for anything that wants it.
MAX_LIVE_ITEMS = 40


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


def format_players(players: list[dict]) -> str:
    """'Malik Willis · QB · MIA'. Empty when nobody was matched.

    The committed data carries exactly one player per item, so the primary
    match is used; the rest stay available on /api/feeds.
    """
    if not players:
        return ""
    first = players[0]
    parts = [first.get("name", ""), first.get("position", ""), first.get("team") or "FA"]
    return f" {DOT} ".join(p for p in parts if p)


def to_news_entry(item: dict) -> dict:
    """One polled item in the page's news shape."""
    title = (item.get("title") or "").strip()
    summary = (item.get("summary") or "").strip()
    text = f"{title} — {summary}" if summary and summary != title else title

    return {
        "kind": "Wire",
        "handle": item.get("source_name", "Wire"),
        "trust": f"Tier {item.get('tier', 2)}",
        "time": format_time(item.get("published")),
        "text": text,
        "players": format_players(item.get("players") or []),
        # Not in the original shape; the page ignores unknown keys. Kept so a
        # reader can always reach the source, which is also the decent thing
        # to do with someone else's reporting.
        "link": item.get("link", ""),
    }


def merge_into_feeds(bundled: dict, items: list[dict], now: datetime) -> dict:
    """Overlay live wire items onto the committed feeds file.

    Only `news` is replaced -- that tab is defined as the raw wire. `alerts`,
    `scout` and the rest carry editorial judgements (status, impact, what it
    means) that a headline cannot supply, so fabricating them would be worse
    than leaving the curated versions in place.
    """
    merged = dict(bundled)
    if not items:
        return merged  # nothing polled yet: serve the committed file untouched

    live = [to_news_entry(i) for i in items[:MAX_LIVE_ITEMS]]

    # Keep curated entries that the wire has not already said.
    seen = {entry["text"] for entry in live}
    curated = [n for n in bundled.get("news", []) if n.get("text") not in seen]

    merged["news"] = live + curated
    merged["updated"] = now.isoformat()
    merged["note"] = (
        "News is polled live from ESPN, Yahoo, Rotowire, ProFootballTalk and CBS. "
        "Other feeds are chat-synced. Data provided by the named sources; "
        "injury and trending data provided by Sleeper."
    )
    return merged
