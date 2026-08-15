"""Live Vegas lines for the FFBets Predictions tab.

ESPN's public scoreboard JSON carries game odds (spread, total, provider)
with no auth -- the same freshness rule as the news wire: the page's const
VEGAS block was hand-curated from the Aug 14 openers and goes stale the
moment a line moves.

The page renders `const VEGAS = [...]` from its own markup, and the tab is
not fed by feeds.json -- so the live board is injected the same way the
FFBets mode flip is: a serve-time string edit of the const in the served
copy of index.html. Disk stays pristine; the fallback on any failure is the
curated block already in the file (stale-but-honest beats blank).

The curated rows carry a `read` column with the owner's prop angles. Those
are judgements a scoreboard cannot supply, so live rows keep the curated
read for the same matchup (matched by team key, ignoring venue notes) and
leave it empty for games the curated block never covered.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger(__name__)

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
# Regular season week 1 -- the draft-prep slate. Phase 3 rotates this weekly.
SEASON_TYPE = 2
WEEK = 1
YEAR = 2026

_FRONTEND_INDEX = Path(__file__).resolve().parent.parent.parent / "frontend" / "index.html"
_VEGAS_BLOCK = re.compile(r"const VEGAS = \[.*?\n\];", re.S)
_CURATED_ROW = re.compile(r'\{ game: "([^"]+)".*?read: "([^"]*)" \}')
_DETAILS = re.compile(r"^([A-Z]{2,4})\s*(-\d+(?:\.\d+)?)$")

DOT = "·"


def _fmt(value: float) -> str:
    """47.0 -> '47', 44.5 -> '44.5'."""
    return f"{value:g}"


def _implied_points(details: str, over_under: float | None) -> tuple[str, float, float] | None:
    match = _DETAILS.match(details.strip())
    if not match or over_under is None:
        return None
    fav, spread = match.group(1), abs(float(match.group(2)))
    fav_pts = (over_under + spread) / 2
    return fav, fav_pts, over_under - fav_pts


def parse_scoreboard(payload: dict) -> list[dict]:
    """Flatten ESPN's scoreboard into the rows the page's VEGAS table shows.

    Kept total: a game with no posted odds still lists with em-dashes --
    an absent game reads as a scraping bug, a dashed line reads as 'Vegas
    has not posted this one', which is the truth.
    """
    rows: list[dict] = []
    for event in payload.get("events") or []:
        competitions = event.get("competitions") or [{}]
        comp = competitions[0]
        home = away = ""
        for side in comp.get("competitors") or []:
            abbrev = (side.get("team") or {}).get("abbreviation", "")
            if side.get("homeAway") == "home":
                home = abbrev
            elif side.get("homeAway") == "away":
                away = abbrev
        game = event.get("shortName") or (f"{away} @ {home}" if home and away else "")
        if not game:
            continue

        odds = (comp.get("odds") or [{}])[0]
        details = (odds.get("details") or "").strip()
        over_under = odds.get("overUnder")

        imp = "—"
        points = _implied_points(details, over_under) if details else None
        if points:
            fav, fav_pts, dog_pts = points
            dog = away if fav == home else home
            imp = f"{fav} {_fmt(fav_pts)} {DOT} {dog} {_fmt(dog_pts)}"

        rows.append(
            {
                "game": game,
                "fav": details or "—",
                "total": _fmt(over_under) if over_under is not None else "—",
                "imp": imp,
                "provider": (odds.get("provider") or {}).get("name", ""),
            }
        )
    return rows


async def fetch(client: httpx.AsyncClient | None = None) -> dict:
    """Week-1 lines from ESPN. Returns the state dict stored with the feed."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(
            timeout=30.0, headers={"User-Agent": "FBBible/1.0 (draft prep, hourly)"}
        )
    try:
        resp = await client.get(
            SCOREBOARD_URL,
            params={"seasontype": SEASON_TYPE, "week": WEEK, "dates": YEAR},
        )
        resp.raise_for_status()
        games = parse_scoreboard(resp.json())
    finally:
        if own_client:
            await client.aclose()

    if not games:
        raise ValueError("ESPN scoreboard returned 0 games")
    return {"fetched_at": datetime.now(UTC).isoformat(), "games": games}


# --- serving the live board ------------------------------------------------


def _game_key(game: str) -> str:
    """'SF @ LAR (Melbourne)' and 'SF @ LAR' are the same matchup."""
    return re.sub(r"\s*\(.*?\)", "", game).strip().upper()


def curated_reads() -> dict[str, str]:
    """The owner's prop-angle column, parsed from the page's own const --
    the page is the source of truth and a copy here would drift."""
    try:
        text = _FRONTEND_INDEX.read_text(encoding="utf-8")
    except OSError:
        return {}
    block = _VEGAS_BLOCK.search(text)
    if not block:
        return {}
    return {_game_key(game): read for game, read in _CURATED_ROW.findall(block.group(0))}


def rows(state: dict, reads: dict[str, str]) -> list[dict]:
    """Live games in the page's VEGAS row shape, curated reads carried over."""
    return [
        {
            "game": g["game"],
            "fav": g["fav"],
            "total": g["total"],
            "imp": g["imp"],
            "read": reads.get(_game_key(g["game"]), ""),
        }
        for g in state.get("games") or []
    ]


# --- live-adjusted TD leans ------------------------------------------------
# The PREDICTIONS const carries the owner's Aug-14 leans with confidence
# numbers built on the opening lines. The leans are judgement and stay
# untouched; the confidence is part-environment, and the environment moves
# with the lines. The honest recompute: shift confidence by how far each
# team's live implied total has moved from the curated opener, and say so on
# the row. No invented model -- a transparent delta from real line movement.

_PRED_BLOCK = re.compile(r"const PREDICTIONS = \[.*?\n\];", re.S)
_PRED_ROW = re.compile(
    r'\{ name: "([^"]+)", meta: "([^"]+)", prop: "([^"]+)", line: "([^"]+)", '
    r'lean: "([^"]+)", conf: (\d+), why: "([^"]*)" \}'
)
_IMP_FIELD = re.compile(r'imp: "([^"]*)"')
_IMP_TEAM = re.compile(r"([A-Z]{2,4})\s+(\d+(?:\.\d+)?)")

# Confidence points per point of implied-total movement. A team's implied
# total moving one point is a real but modest scoring-environment shift.
CONF_PER_POINT = 2.0
CONF_FLOOR, CONF_CEIL = 35, 90
# Below this the movement is book noise, not an environment change.
MIN_MOVE = 0.5

PRED_CAPTION = (
    "Week 1 touchdown predictions — model lean vs the line, "
    "with confidence from last season's TD rates and matchup."
)
PRED_LIVE_CAPTION = (
    "Week 1 touchdown predictions — lean set Aug 14; confidence adjusted "
    "live as implied totals move (ESPN odds)."
)


def _implied_map(imp_strings: list[str]) -> dict[str, float]:
    """['SEA 24 · NE 20.5', ...] -> {'SEA': 24.0, 'NE': 20.5, ...}."""
    teams: dict[str, float] = {}
    for imp in imp_strings:
        for team, points in _IMP_TEAM.findall(imp):
            teams[team] = float(points)
    return teams


def curated_predictions() -> list[dict]:
    """The owner's TD-lean rows, parsed from the page's own const."""
    try:
        text = _FRONTEND_INDEX.read_text(encoding="utf-8")
    except OSError:
        return []
    block = _PRED_BLOCK.search(text)
    if not block:
        return []
    return [
        {
            "name": name,
            "meta": meta,
            "prop": prop,
            "line": line,
            "lean": lean,
            "conf": int(conf),
            "why": why,
        }
        for name, meta, prop, line, lean, conf, why in _PRED_ROW.findall(block.group(0))
    ]


def live_implied(live_rows: list[dict]) -> dict[str, float]:
    """Implied totals from the live board's rendered rows."""
    return _implied_map([r.get("imp", "") for r in live_rows])


def curated_implied() -> dict[str, float]:
    """Implied totals from the committed VEGAS openers -- the baseline the
    curated confidence numbers were set against."""
    try:
        text = _FRONTEND_INDEX.read_text(encoding="utf-8")
    except OSError:
        return {}
    block = _VEGAS_BLOCK.search(text)
    if not block:
        return {}
    return _implied_map(_IMP_FIELD.findall(block.group(0)))


def adjust_predictions(
    preds: list[dict], baseline: dict[str, float], live: dict[str, float]
) -> list[dict]:
    """Shift each row's confidence by its team's implied-total movement.

    A team missing from either board (line not posted, or not in the curated
    openers) leaves the row exactly as curated -- adjusting on a guess would
    be the false positive this project bans."""
    adjusted = []
    for pred in preds:
        row = dict(pred)
        team = pred["meta"].split(DOT)[-1].strip()
        base_pts, live_pts = baseline.get(team), live.get(team)
        if base_pts is not None and live_pts is not None:
            delta = live_pts - base_pts
            if abs(delta) >= MIN_MOVE:
                shifted = pred["conf"] + delta * CONF_PER_POINT
                row["conf"] = int(max(CONF_FLOOR, min(CONF_CEIL, round(shifted))))
                row["why"] = (
                    f"{pred['why']} Line move: {team} implied {_fmt(base_pts)} → {_fmt(live_pts)}."
                )
        adjusted.append(row)
    return adjusted


def inject_predictions(html: str, adjusted: list[dict]) -> str:
    """Swap the curated PREDICTIONS const for the live-adjusted rows."""
    if not adjusted:
        return html
    replacement = f"const PREDICTIONS = {json.dumps(adjusted)};"
    swapped, count = _PRED_BLOCK.subn(lambda _: replacement, html, count=1)
    if not count:
        return html
    return swapped.replace(PRED_CAPTION, PRED_LIVE_CAPTION, 1)


CURATED_CAPTION = "DraftKings openers via ESPN — lines move; re-sync before kickoff"
LIVE_CAPTION = "Live via ESPN — refreshed with every news sync"
LIVE_SOURCE = "ESPN live odds — synced with the news poll"

# The page's own Data health seed row for this feed (superseded by the
# feeds.json overlay, but the fallback must not claim live data is a
# two-day-old chat sync).
_META_ROW = re.compile(
    r'(\{ feed: "Vegas lines", asOf: ")[^"]*(", maxAgeH: \d+, source: ")[^"]*(")'
)


def central_stamp(iso: str | None) -> str:
    """fetched_at -> the naive Central 'YYYY-MM-DDTHH:MM' Data health reads."""
    if not iso:
        return ""
    try:
        local = datetime.fromisoformat(iso).astimezone(ZoneInfo("America/Chicago"))
    except ValueError:
        return ""
    return f"{local:%Y-%m-%dT%H:%M}"


def inject(html: str, live_rows: list[dict], stamp: str = "") -> str:
    """Swap the curated VEGAS const for the live board in the served page.

    json.dumps output is valid JS. If the const's literal shape ever changes
    under a design-project sync, the regex misses and the page serves its
    committed block -- stale-but-honest, and test_vegas notices."""
    if not live_rows:
        return html
    replacement = f"const VEGAS = {json.dumps(live_rows)};"
    swapped, count = _VEGAS_BLOCK.subn(lambda _: replacement, html, count=1)
    if not count:
        return html
    swapped = swapped.replace(CURATED_CAPTION, LIVE_CAPTION, 1)
    if stamp:
        swapped = _META_ROW.sub(
            lambda m: f"{m.group(1)}{stamp}{m.group(2)}{LIVE_SOURCE}{m.group(3)}",
            swapped,
            count=1,
        )
    return swapped
