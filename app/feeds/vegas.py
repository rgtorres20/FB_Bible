"""Live Vegas lines for the FFBets tab, from ESPN's public scoreboard.

ESPN's site API serves current-week NFL games with DraftKings odds -- spread
and total -- as plain JSON, no auth. That replaces the committed VEGAS table
in the page, which was written on Aug 13 and can only rot.

The page's fifth column ("Prop angle") is editorial, and the wire rule
applies here the same as everywhere else: a fetch cannot supply judgement.
Live rows carry factual reads only -- slate superlatives (highest/lowest
total, heaviest favorite) and kickoff times -- never invented betting takes.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx

URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
CENTRAL = ZoneInfo("America/Chicago")
DOT = "·"

_SPREAD = re.compile(r"^([A-Z]{2,4})\s+(-?\d+(?:\.\d+)?)$")


async def fetch(client: httpx.AsyncClient | None = None) -> dict:
    """Current scoreboard with odds, reduced to the page's table shape."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(
            timeout=30.0, headers={"User-Agent": "FBBible/1.0 (draft prep, hourly)"}
        )
    try:
        response = await client.get(URL)
        response.raise_for_status()
        payload = response.json()
    finally:
        if own_client:
            await client.aclose()

    games = build_rows(payload)
    if not games:
        raise ValueError("scoreboard had 0 parseable games")

    week = payload.get("week", {}).get("number")
    season_type = payload.get("season", {}).get("type")
    label = f"{'Preseason ' if season_type == 1 else ''}Week {week}" if week else ""
    return {
        "fetched_at": datetime.now(UTC).isoformat(),
        "week_label": label,
        "games": games,
    }


def implied(details: str, total: float | None) -> tuple[str, str]:
    """('BUF -3', 38.5) -> ('BUF -3', 'BUF 20.8 · CAR 17.8'-style favourite half).

    Returns (fav, implied-points-for-favourite) where implied is '—' whenever
    the spread or total is missing or not a plain point spread.
    """
    details = (details or "").strip()
    if not details:
        return "—", "—"
    match = _SPREAD.match(details)
    if not match or total is None:
        return details, "—"
    team, spread = match.group(1), float(match.group(2))
    fav_points = round((total - spread) / 2, 1)  # spread is negative for the favourite
    dog_points = round(total - fav_points, 1)
    return details, f"{team} {fav_points:g} {DOT} opp {dog_points:g}"


def _kickoff(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        stamp = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(CENTRAL)
    except ValueError:
        return ""
    hour = stamp.hour % 12 or 12
    meridiem = "AM" if stamp.hour < 12 else "PM"
    return f"{stamp:%a} {hour}:{stamp:%M} {meridiem} CT"


def build_rows(payload: dict) -> list[dict]:
    rows = []
    for event in payload.get("events", []):
        try:
            competition = (event.get("competitions") or [{}])[0]
            sides = {
                c.get("homeAway"): c.get("team", {}).get("abbreviation", "?")
                for c in competition.get("competitors", [])
            }
            if "home" not in sides or "away" not in sides:
                continue
            odds = (competition.get("odds") or [{}])[0]
            total = odds.get("overUnder")
            fav, imp = implied(odds.get("details") or "", total)
            rows.append(
                {
                    "game": f"{sides['away']} @ {sides['home']}",
                    "fav": fav,
                    "total": f"{total:g}" if isinstance(total, int | float) else "—",
                    "imp": imp,
                    "read": _kickoff(event.get("date")),
                    "_ou": total if isinstance(total, int | float) else None,
                }
            )
        except Exception:  # noqa: BLE001 - one malformed event must not sink the slate
            continue

    _annotate_superlatives(rows)
    for row in rows:
        row.pop("_ou", None)
    return rows


def _annotate_superlatives(rows: list[dict]) -> None:
    """Factual slate context in the read column, never a betting take."""
    with_ou = [r for r in rows if r["_ou"] is not None]
    if len(with_ou) >= 2:
        high = max(with_ou, key=lambda r: r["_ou"])
        low = min(with_ou, key=lambda r: r["_ou"])
        high["read"] = f"Highest total on the slate {DOT} {high['read']}".rstrip(f" {DOT}")
        low["read"] = f"Lowest total on the slate {DOT} {low['read']}".rstrip(f" {DOT}")

    def spread_size(row: dict) -> float:
        match = _SPREAD.match(row["fav"])
        return abs(float(match.group(2))) if match else 0.0

    spreads = [r for r in rows if spread_size(r) > 0]
    if spreads:
        heavy = max(spreads, key=spread_size)
        if spread_size(heavy) >= 6:
            heavy["read"] = f"Heaviest favorite of the slate {DOT} {heavy['read']}".rstrip(
                f" {DOT}"
            )
