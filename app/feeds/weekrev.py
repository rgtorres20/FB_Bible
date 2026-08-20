"""The Week review tab, fed live scores instead of a frozen seed.

The page was wired for this from day one -- it renders
`F.weekrev || WEEKREV_SEED`, and the seed's own footer promises "results
and stat lines land here on the next sync" -- but nothing ever served a
`weekrev` key. Now the sync-feeds runner fetches ESPN's *current-week*
scoreboard (the same runner-push route as the Vegas slate: ESPN 403s
Vercel's IPs) and POSTs it to /internal/scores; the overlay builds the
tab's object from it.

Honesty split, decided deliberately:

- **games** are fully live: real scores, FINAL/quarter/kickoff status,
  the broadcast as the only note -- facts, never invented analysis.
- **stars** (the "high performers -- fantasy read" column) stay the
  owner's curated seed, passed through from the page itself: a real
  performer ranking needs per-player box scores this feed does not
  carry. If the seed cannot be parsed, no weekrev is served at all and
  the page falls back to its complete seed -- live games are not worth
  losing the curated column for.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

CENTRAL = ZoneInfo("America/Chicago")

URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"

_FRONTEND_INDEX = Path(__file__).resolve().parent.parent.parent / "frontend" / "index.html"
_STARS_BLOCK = re.compile(r"const WEEKREV_SEED = \{.*?stars:\s*\[(.*?)\n\s*\]\s*\n\};", re.S)
_STAR_ROW = re.compile(
    r'\{\s*name:\s*"([^"]*)",\s*meta:\s*"([^"]*)",\s*line:\s*"([^"]*)",'
    r'\s*read:\s*"([^"]*)",\s*src:\s*"([^"]*)"\s*\}'
)


async def fetch_scores(client: httpx.AsyncClient | None = None) -> dict:
    """The current week's scoreboard, reduced to the tab's games shape.

    No week/seasontype pins -- ESPN returns whatever week it is, which is
    exactly what a review tab wants: preseason weeks now, real weeks in
    September, playoffs in January.
    """
    own_client = client is None
    if own_client:
        # Same honest UA rules as vegas.fetch -- see the comment there.
        client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "FBBible/1.0 (personal draft tool, hourly)"},
        )
    try:
        response = await client.get(URL)
        response.raise_for_status()
        payload = response.json()
    finally:
        if own_client:
            await client.aclose()

    games = build_games(payload)
    if not games:
        raise ValueError("scoreboard had 0 parseable games")

    week = payload.get("week", {}).get("number")
    season_type = payload.get("season", {}).get("type")
    prefix = "Preseason " if season_type == 1 else "Playoffs " if season_type == 3 else ""
    return {
        "fetched_at": datetime.now(UTC).isoformat(),
        "week_label": f"{prefix}Week {week}" if week else "This week",
        "range": _range(payload),
        "games": games,
    }


def _central(iso: str) -> datetime | None:
    try:
        return datetime.fromisoformat((iso or "").replace("Z", "+00:00")).astimezone(CENTRAL)
    except ValueError:
        return None


def _range(payload: dict) -> str:
    stamps = sorted(
        d for d in (_central(e.get("date", "")) for e in payload.get("events", [])) if d
    )
    if not stamps:
        return ""
    first, last = stamps[0], stamps[-1]
    if first.date() == last.date():
        return f"{first:%a} {first:%b} {first.day}"
    return f"{first:%a} {first:%b} {first.day} – {last:%a} {last:%b} {last.day}"


def build_games(payload: dict) -> list[dict]:
    """Events in the page's row shape: finals show the score, upcoming
    games show the matchup with a Central kickoff, live games show the
    clock ESPN reports. The note is the broadcast -- a fact -- or blank."""
    rows = []
    for event in payload.get("events", []):
        try:
            competition = (event.get("competitions") or [{}])[0]
            sides = {c.get("homeAway"): c for c in competition.get("competitors", [])}
            if "home" not in sides or "away" not in sides:
                continue
            away, home = sides["away"], sides["home"]
            away_ab = away.get("team", {}).get("abbreviation", "?")
            home_ab = home.get("team", {}).get("abbreviation", "?")

            status = (event.get("status") or {}).get("type") or {}
            state = status.get("state")
            local = _central(event.get("date", ""))
            day = f"{local:%a} {local:%b} {local.day}" if local else ""

            if state == "post":
                score = f"{away_ab} {away.get('score', '?')} · {home_ab} {home.get('score', '?')}"
                label = "FINAL"
                detail = status.get("shortDetail") or ""
                if "OT" in detail.upper():
                    label = "FINAL · OT"
            elif state == "in":
                score = f"{away_ab} {away.get('score', '?')} · {home_ab} {home.get('score', '?')}"
                label = status.get("shortDetail") or "LIVE"
            else:
                score = f"{away_ab} @ {home_ab}"
                hour = local.hour % 12 or 12 if local else ""
                label = f"{hour}:{local:%M} {'AM' if local.hour < 12 else 'PM'} CT" if local else ""

            broadcasts = competition.get("broadcasts") or []
            note = (broadcasts[0].get("names") or [""])[0] if broadcasts else ""
            rows.append({"day": day, "score": score, "status": label, "note": note})
        except Exception:  # noqa: BLE001 - one malformed event must not sink the review
            continue
    return rows


def curated_stars() -> list[dict]:
    """The owner's high-performer reads, parsed out of the page's own seed
    so the served object keeps the column the page would otherwise show."""
    try:
        text = _FRONTEND_INDEX.read_text(encoding="utf-8")
    except OSError:
        return []
    block = _STARS_BLOCK.search(text)
    if not block:
        return []
    return [
        {"name": n, "meta": m, "line": ln, "read": r, "src": s}
        for n, m, ln, r, s in _STAR_ROW.findall(block.group(1))
    ]


def build(scores_state: dict | None, stars: list[dict] | None = None) -> dict | None:
    """The full F.weekrev object, or None -- and None means the page keeps
    its complete seed, which beats live games beside an empty column."""
    games = (scores_state or {}).get("games") or []
    stars = curated_stars() if stars is None else stars
    if not games or not stars:
        return None
    return {
        "week": scores_state.get("week_label") or "This week",
        "range": scores_state.get("range") or "",
        "games": games,
        "stars": stars,
    }
