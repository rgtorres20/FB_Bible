"""Live Vegas lines for the FFBets tab, from ESPN's public scoreboard.

ESPN's site API serves NFL games with DraftKings odds -- spread and total --
as plain JSON, no auth. That replaces the committed VEGAS table in the page,
which was written on Aug 13 and can only rot. The fetch is pinned to the
regular-season Week 1 slate: that is what the tab claims to show and what
draft prep needs. Phase 3 rotates it weekly.

Delivery quirk, hard-won (verified live 2026-08-15): ESPN 403s Vercel's IP
range outright, and ALSO 403s faked browser headers from anywhere (TLS
fingerprint check), while the honest tool UA passes from residential and
GitHub-runner IPs. So the deployment never fetches its own lines -- the
sync-feeds workflow runner fetches (scripts/push_vegas.py) and POSTs the
slate to /internal/vegas, and the overlay serves it to the page via the
`vegas: (F.vegas || VEGAS)` rebind in app_page.

The page's fifth column ("Prop angle") is editorial, and the wire rule
applies here the same as everywhere else: a fetch cannot supply judgement.
Live rows carry factual reads only -- slate superlatives (highest/lowest
total, heaviest favorite) and kickoff times -- never invented betting takes.
The owner's prop angles live on in the PREDICTIONS table below it, whose
confidence tracks these same lines (see the TD-leans section).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from .. import config

URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
# Regular season week 1 -- the draft-prep slate the tab claims to show.
SEASON_TYPE = 2
WEEK = 1
YEAR = config.SEASON_YEAR

CENTRAL = ZoneInfo("America/Chicago")
DOT = "·"

_FRONTEND_INDEX = Path(__file__).resolve().parent.parent.parent / "frontend" / "index.html"
_SPREAD = re.compile(r"^([A-Z]{2,4})\s+(-?\d+(?:\.\d+)?)$")


async def fetch(client: httpx.AsyncClient | None = None) -> dict:
    """The Week 1 scoreboard with odds, reduced to the page's table shape."""
    own_client = client is None
    if own_client:
        # Plain honest UA, verified working from residential and GitHub
        # runner IPs. Do NOT fake browser headers: ESPN's bot detection 403s
        # a Chrome UA whose TLS fingerprint is not Chrome (verified live
        # 2026-08-15 -- the "browser headers" version broke fetches that the
        # tool UA passed). Vercel's IP range is blocked outright regardless
        # of headers, which is why the slate is pushed from the sync-feeds
        # workflow runner instead (scripts/push_vegas.py).
        client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "FBBible/1.0 (personal draft tool, hourly)"},
        )
    try:
        response = await client.get(
            URL, params={"seasontype": SEASON_TYPE, "week": WEEK, "dates": YEAR}
        )
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


def implied(details: str, total: float | None, away: str = "", home: str = "") -> tuple[str, str]:
    """('BUF -3', 38.5) -> ('BUF -3', 'BUF 20.8 · CAR 17.7').

    Returns (fav, implied-points) where implied is '—' whenever the spread
    or total is missing or not a plain point spread. The underdog is named
    when the caller supplies the matchup; 'opp' otherwise.
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
    dog = (home if team == away else away) or "opp"
    return details, f"{team} {fav_points:g} {DOT} {dog} {dog_points:g}"


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
            sides: dict[str, dict] = {
                c.get("homeAway"): c.get("team", {}) for c in competition.get("competitors", [])
            }
            if "home" not in sides or "away" not in sides:
                continue
            away = sides["away"].get("abbreviation", "?")
            home = sides["home"].get("abbreviation", "?")
            odds = (competition.get("odds") or [{}])[0]
            total = odds.get("overUnder")
            fav, imp = implied(odds.get("details") or "", total, away, home)
            broadcasts = competition.get("broadcasts") or []
            rows.append(
                {
                    "game": f"{away} @ {home}",
                    "fav": fav,
                    "total": f"{total:g}" if isinstance(total, int | float) else "—",
                    "imp": imp,
                    "read": _kickoff(event.get("date")),
                    # The schedule tab reads these; the odds table ignores them.
                    "kickoff": event.get("date", ""),
                    "away_name": sides["away"].get("displayName", ""),
                    "home_name": sides["home"].get("displayName", ""),
                    "tv": ((broadcasts[0].get("names") or [""])[0] if broadcasts else ""),
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


def central_stamp(iso: str | None) -> str:
    """fetched_at -> the naive Central 'YYYY-MM-DDTHH:MM' Data health reads."""
    if not iso:
        return ""
    try:
        local = datetime.fromisoformat(iso).astimezone(CENTRAL)
    except ValueError:
        return ""
    return f"{local:%Y-%m-%dT%H:%M}"


# --- the served page's odds caption ----------------------------------------
# The table's data goes live through the feeds.json overlay (F.vegas), but
# the caption above it is template text still describing the Aug-14 openers.
# When live lines exist the served copy says so instead.

CURATED_CAPTION = "DraftKings openers via ESPN — lines move; re-sync before kickoff"
LIVE_CAPTION = "Live via ESPN — refreshed with every news sync"

# How old a stored slate may be and still be called live. The push runs
# with the 15-minute sync, so anything past a few hours means it is
# failing -- which it did, silently, for a day from Aug 21 while the page
# kept saying "refreshed with every news sync" over a frozen slate. Six
# hours is the same budget Data health gives the server wire.
LIVE_MAX_AGE_HOURS = 6.0


def is_live(state: dict | None, now: datetime | None = None) -> bool:
    """Whether a stored slate is fresh enough to be called live.

    An unstamped slate is not live: the claim needs evidence, and its
    absence is not evidence.
    """
    stamp = (state or {}).get("fetched_at")
    if not stamp:
        return False
    try:
        fetched = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return False
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=UTC)
    now = now or datetime.now(UTC)
    return (now - fetched).total_seconds() <= LIVE_MAX_AGE_HOURS * 3600


def stale_caption(state: dict | None) -> str:
    """What the caption says when the slate is real but no longer fresh.

    Naming the age beats both alternatives: "live" would be false, and
    dropping the numbers would throw away a slate that is still the last
    real one anybody has.
    """
    stamp = central_stamp((state or {}).get("fetched_at"))
    return f"Via ESPN — last refreshed {stamp}" if stamp else "Via ESPN — refresh time unknown"


def refresh_caption(html: str, state: dict | None = None) -> str:
    """Swap the curated caption for one that describes the real slate.

    `state` is optional only so the older call shape keeps working; pass
    it, or the caption claims a freshness nothing checked.
    """
    caption = LIVE_CAPTION if (state is None or is_live(state)) else stale_caption(state)
    return html.replace(CURATED_CAPTION, caption, 1)


# --- live-adjusted TD leans ------------------------------------------------
# The PREDICTIONS const carries the owner's Aug-14 leans with confidence
# numbers built on the opening lines. The leans are judgement and stay
# untouched; the confidence is part-environment, and the environment moves
# with the lines. The honest recompute: shift confidence by how far each
# team's live implied total has moved from the curated opener, and say so on
# the row. No invented model -- a transparent delta from real line movement.

_VEGAS_BLOCK = re.compile(r"const VEGAS = \[.*?\n\];", re.S)
_PRED_BLOCK = re.compile(r"const PREDICTIONS = \[.*?\n\];", re.S)
_PRED_ROW = re.compile(
    r'\{ name: "([^"]+)", meta: "([^"]+)", prop: "([^"]+)", line: "([^"]+)", '
    r'lean: "([^"]+)", conf: (\d+), why: "([^"]*)" \}'
)
_IMP_FIELD = re.compile(r'imp: "([^"]*)"')
_IMP_TEAM = re.compile(r"([A-Z]{2,4})\s+(\d+(?:\.\d+)?)")
_GAME_TEAMS = re.compile(r"^([A-Z]{2,4}) @ ([A-Z]{2,4})")

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


def _fmt(value: float) -> str:
    """47.0 -> '47', 44.5 -> '44.5'."""
    return f"{value:g}"


def curated_predictions() -> list[dict]:
    """The owner's TD-lean rows, parsed from the page's own const -- the
    page is the source of truth and a copy here would drift."""
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
    teams: dict[str, float] = {}
    for imp in _IMP_FIELD.findall(block.group(0)):
        for team, points in _IMP_TEAM.findall(imp):
            teams[team] = float(points)
    return teams


def matchup_teams(game: str | None) -> tuple[str, str] | None:
    """('NE @ SEA') -> ('NE', 'SEA'), or None when the row is not a game.

    Public because `previews` needs it and was reaching into the private
    regex to get it -- coupling itself to a name this module never
    promised to keep (tests/test_boundaries.py, Aug 21).
    """
    match = _GAME_TEAMS.match(game or "")
    return (match.group(1), match.group(2)) if match else None


def implied_by_team(games: list[dict]) -> dict[str, float]:
    """Per-team implied totals recomputed from stored rows' fav + total.

    Works on the sanitized five-string-column rows: 'NE @ SEA' + 'SEA -3.5'
    + '44.5' names both sides. Games without a parseable spread and total
    contribute nothing -- no baseline, no guess."""
    teams: dict[str, float] = {}
    for row in games:
        game = _GAME_TEAMS.match(row.get("game") or "")
        spread = _SPREAD.match((row.get("fav") or "").strip())
        try:
            total = float(row.get("total") or "")
        except ValueError:
            continue
        if not game or not spread:
            continue
        away, home = game.group(1), game.group(2)
        fav = spread.group(1)
        if fav not in (away, home):
            # Divergent abbreviations (WSH vs WAS) would otherwise assign
            # the dog total to the wrong side and invent a phantom team.
            continue
        fav_points = round((total - float(spread.group(2))) / 2, 1)
        dog = home if fav == away else away
        teams[fav] = fav_points
        teams[dog] = round(total - fav_points, 1)
    return teams


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
            # Direction follows the lean: a rising implied total supports an
            # OVER and undermines an UNDER. Without this flip, Mahomes-under
            # gained confidence when KC's scoring environment improved.
            if pred.get("lean", "").upper().startswith("UNDER"):
                delta = -delta
            if abs(delta) >= MIN_MOVE:
                shifted = pred["conf"] + delta * CONF_PER_POINT
                row["conf"] = int(max(CONF_FLOOR, min(CONF_CEIL, round(shifted))))
                row["why"] = (
                    f"{pred['why']} Line move: {team} implied {_fmt(base_pts)} → {_fmt(live_pts)}."
                )
        adjusted.append(row)
    return adjusted


def lean_review_rows(games: list[dict]) -> list[dict]:
    """Each curated TD lean beside the live implied total for its team --
    what the hourly annotate job sends the model. Leans with no posted line
    are dropped rather than sent: without a live number there is nothing to
    check the lean against, and asking anyway invites the model to supply
    one from memory. (Moved here from scripts/review_predictions.py when
    the annotation calls were consolidated -- the work list is assembled
    server-side like every other AI surface's.)"""
    implied = implied_by_team(games)
    out = []
    for pred in curated_predictions():
        team = pred["meta"].split(DOT)[-1].strip()
        live = implied.get(team)
        if live is None:
            continue  # no posted line: nothing to check it against
        out.append(
            {
                "player": pred["name"],
                "team": team,
                "prop": pred["prop"],
                "line": pred["line"],
                "lean": pred["lean"],
                "implied_team_total_now": live,
            }
        )
    return out


def apply_reviews(preds: list[dict], reviews: dict[str, str] | None) -> list[dict]:
    """Append an AI sanity-check clause to a row's why, and nothing else.

    The lean and the confidence stay exactly as computed. A model that
    disagrees with the owner says so in its own labelled clause -- it does
    not get to quietly rewrite the call, which is the whole reason the
    leans were never handed to it in the first place.
    """
    if not reviews:
        return preds
    out = []
    for pred in preds:
        note = (reviews.get(pred["name"]) or "").strip()
        row = dict(pred)
        if note:
            row["why"] = f"{pred['why']} AI check: {note}"
        out.append(row)
    return out


def inject_predictions(html: str, adjusted: list[dict]) -> str:
    """Swap the curated PREDICTIONS const for the live-adjusted rows."""
    if not adjusted:
        return html
    replacement = f"const PREDICTIONS = {json.dumps(adjusted)};"
    swapped, count = _PRED_BLOCK.subn(lambda _: replacement, html, count=1)
    if not count:
        return html
    return swapped.replace(PRED_CAPTION, PRED_LIVE_CAPTION, 1)


# --- the Week 1 schedule tab -----------------------------------------------
# Same payload, second surface: the WEEK1 const was hand-typed from the May
# schedule release. Kickoff, teams and network all arrive with the odds; the
# per-game fantasy notes are the owner's and ride along by matchup.

_WEEK1_BLOCK = re.compile(r"const WEEK1 = \[.*?\n\];", re.S)
_WEEK1_ROW = re.compile(
    r'\{ day: "[^"]*", time: "[^"]*", away: "([^"]+)", home: "([^"]+)", '
    r'tv: "([^"]*)", note: "([^"]*)" \}'
)
_SCHED_META_ROW = re.compile(
    r'(\{ feed: "Week 1 schedule", asOf: ")[^"]*(", maxAgeH: \d+, source: ")[^"]*(")'
)
SCHED_LIVE_SOURCE = "ESPN scoreboard — live kickoff times"


def _kickoff_central(iso: str) -> tuple[str, str]:
    """'2026-09-13T17:00Z' -> ('Sun Sep 13', '12:00 PM CT')."""
    try:
        local = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(CENTRAL)
    except ValueError:
        return "", ""
    hour = local.hour % 12 or 12
    meridiem = "AM" if local.hour < 12 else "PM"
    return f"{local:%a} {local:%b} {local.day}", f"{hour}:{local:%M} {meridiem} CT"


def curated_week1() -> dict[str, dict]:
    """The owner's notes (and TV as fallback) per matchup, from the page."""
    try:
        text = _FRONTEND_INDEX.read_text(encoding="utf-8")
    except OSError:
        return {}
    block = _WEEK1_BLOCK.search(text)
    if not block:
        return {}
    return {
        f"{away} @ {home}": {"tv": tv, "note": note}
        for away, home, tv, note in _WEEK1_ROW.findall(block.group(0))
    }


def schedule_rows(
    state: dict,
    curated: dict[str, dict] | None = None,
    previews: dict[str, str] | None = None,
) -> list[dict]:
    """Live games in the page's WEEK1 shape. Games without a kickoff or team
    names are skipped -- a half-known row would render as a broken line, and
    the curated const remains the fallback whenever this returns empty.

    `previews` is AI matchup prose keyed 'Away Name @ Home Name' (see
    app/feeds/previews.py). It appends to the note prefixed "AI preview:" --
    a labelled clause beside the owner's note, same contract as "AI check:".
    """
    curated = curated if curated is not None else curated_week1()
    previews = previews or {}
    rows_out: list[dict] = []
    for game in state.get("games") or []:
        day, time = _kickoff_central(game.get("kickoff", ""))
        away, home = game.get("away_name", ""), game.get("home_name", "")
        if not (day and away and home):
            continue
        known = curated.get(f"{away} @ {home}", {})
        note = known.get("note", "")
        ai = previews.get(f"{away} @ {home}")
        if ai:
            note = f"{note} AI preview: {ai}" if note else f"AI preview: {ai}"
        rows_out.append(
            {
                "day": day,
                "time": time,
                "away": away,
                "home": home,
                # ESPN's broadcast field when present, the curated network
                # otherwise -- never invented.
                "tv": game.get("tv") or known.get("tv", ""),
                "note": note,
            }
        )
    return rows_out


def inject_schedule(html: str, sched: list[dict], stamp: str = "") -> str:
    """Swap the curated WEEK1 const for live kickoff data in the served page."""
    if not sched:
        return html
    replacement = f"const WEEK1 = {json.dumps(sched)};"
    swapped, count = _WEEK1_BLOCK.subn(lambda _: replacement, html, count=1)
    if not count:
        return html
    if stamp:
        swapped = _SCHED_META_ROW.sub(
            lambda m: f"{m.group(1)}{stamp}{m.group(2)}{SCHED_LIVE_SOURCE}{m.group(3)}",
            swapped,
            count=1,
        )
    return swapped
