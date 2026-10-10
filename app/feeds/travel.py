"""Travel and rest: how far each team has flown, and how fresh it is.

Owner, Oct 10: "if we look at travel of team it becomes a factor in play
the next game -- this week the Cowboys had traveled [a lot] in 3 games when
the opponent had 3 home games and no travel ... how can we look at that in
another column for team intel or best props for games".

Everything here is measured from the schedule, never estimated:

- **the schedule** is ESPN's scoreboard, one regular-season week at a time
  (probe runs 52-56, 2026-10-10: every event carries `date`, both
  competitors with `homeAway` and `abbreviation`, `neutralSite`, and a
  `venue` with `address.city/state/country` and `indoor`). ESPN 403s
  Vercel, so the runner fetches (scripts/push_vegas.py) and pushes to
  /internal/schedule; each week is fetched once, and the current and next
  week again on every run so a flexed kickoff lands.
- **where a game is played** is the home team's stadium, unless ESPN marks
  it a neutral site or puts it outside the USA -- then it is the venue's
  city, looked up in NEUTRAL_CITIES. A city that table does not carry is
  reported as "distance not mapped", never guessed.
- **distance** is the great-circle mileage between stadiums. A road game
  counts as a round trip (home, venue, home); this week's trip counts its
  outbound leg only, since the return has not happened.

The reads drawn from those numbers -- which gap is big enough to call an
edge -- are written rules, named where they render and recorded in
docs/ASSUMPTIONS.md. Nothing here moves a projection.
"""

from __future__ import annotations

import math
import unicodedata
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from .. import config
from .clock import CENTRAL

URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
SEASON_TYPE = 2
WEEKS = tuple(range(1, 19))
# How many weeks the runner backfills per run: a scoreboard is ~270KB, and
# the season only has to be fetched once.
MAX_WEEKS_PER_RUN = 6

# Every club's home stadium -- (lat, lon, IANA zone), keyed by ESPN's own
# abbreviation so it joins the slate and the Team intel rows (WSH, not
# WAS). Fixed facts, not a feed: a stadium does not move mid-season.
# The Rams and Chargers share SoFi; the Giants and Jets share MetLife.
STADIUMS: dict[str, tuple[float, float, str]] = {
    "ARI": (33.5276, -112.2626, "America/Phoenix"),
    "ATL": (33.7554, -84.4008, "America/New_York"),
    "BAL": (39.2780, -76.6227, "America/New_York"),
    "BUF": (42.7738, -78.7870, "America/New_York"),
    "CAR": (35.2258, -80.8528, "America/New_York"),
    "CHI": (41.8623, -87.6167, "America/Chicago"),
    "CIN": (39.0955, -84.5161, "America/New_York"),
    "CLE": (41.5061, -81.6995, "America/New_York"),
    "DAL": (32.7473, -97.0945, "America/Chicago"),
    "DEN": (39.7439, -105.0201, "America/Denver"),
    "DET": (42.3400, -83.0456, "America/Detroit"),
    "GB": (44.5013, -88.0622, "America/Chicago"),
    "HOU": (29.6847, -95.4107, "America/Chicago"),
    "IND": (39.7601, -86.1639, "America/Indiana/Indianapolis"),
    "JAX": (30.3239, -81.6373, "America/New_York"),
    "KC": (39.0489, -94.4839, "America/Chicago"),
    "LAC": (33.9535, -118.3392, "America/Los_Angeles"),
    "LAR": (33.9535, -118.3392, "America/Los_Angeles"),
    "LV": (36.0909, -115.1833, "America/Los_Angeles"),
    "MIA": (25.9580, -80.2389, "America/New_York"),
    "MIN": (44.9738, -93.2581, "America/Chicago"),
    "NE": (42.0909, -71.2643, "America/New_York"),
    "NO": (29.9511, -90.0812, "America/Chicago"),
    "NYG": (40.8128, -74.0742, "America/New_York"),
    "NYJ": (40.8128, -74.0742, "America/New_York"),
    "PHI": (39.9008, -75.1675, "America/New_York"),
    "PIT": (40.4468, -80.0158, "America/New_York"),
    "SEA": (47.5952, -122.3316, "America/Los_Angeles"),
    "SF": (37.4030, -121.9700, "America/Los_Angeles"),
    "TB": (27.9759, -82.5033, "America/New_York"),
    "TEN": (36.1665, -86.7713, "America/Chicago"),
    "WSH": (38.9077, -76.8645, "America/New_York"),
}

# Cities that have hosted, or are named to host, neutral-site and
# international games -- city centre, which is within a few miles of any
# stadium there and far inside the precision a transatlantic trip needs.
NEUTRAL_CITIES: dict[str, tuple[float, float, str]] = {
    "london": (51.5072, -0.1276, "Europe/London"),
    "dublin": (53.3498, -6.2603, "Europe/Dublin"),
    "berlin": (52.5200, 13.4050, "Europe/Berlin"),
    "munich": (48.1351, 11.5820, "Europe/Berlin"),
    "frankfurt": (50.1109, 8.6821, "Europe/Berlin"),
    "madrid": (40.4168, -3.7038, "Europe/Madrid"),
    "paris": (48.8566, 2.3522, "Europe/Paris"),
    "sao paulo": (-23.5505, -46.6333, "America/Sao_Paulo"),
    "rio de janeiro": (-22.9068, -43.1729, "America/Sao_Paulo"),
    "mexico city": (19.4326, -99.1332, "America/Mexico_City"),
    "melbourne": (-37.8136, 144.9631, "Australia/Melbourne"),
    "toronto": (43.6532, -79.3832, "America/Toronto"),
}

# --- the written rules (docs/ASSUMPTIONS.md) ------------------------------
# The window: this game and the two before it -- "three games", as the
# owner framed it.
WINDOW = 3
# A rest gap this many days wider than the opponent's is called an edge.
REST_EDGE_DAYS = 3
# A third straight game away from home, against a team at home.
ROAD_STREAK = 3
# This many more miles over the window than the opponent.
MILES_EDGE = 2500
# Two or more time zones east, kicking off before this local hour.
BODY_CLOCK_ZONES = 2
EARLY_LOCAL_HOUR = 14
# Thirteen days between games is a bye week.
BYE_DAYS = 13


def _norm(city: str) -> str:
    folded = unicodedata.normalize("NFKD", city or "").encode("ascii", "ignore").decode()
    return " ".join(folded.lower().split())


def _miles(a: tuple[float, float, str], b: tuple[float, float, str]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def _when(iso: str) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


# --- the schedule, as the runner pushes it --------------------------------


def reduce_week(payload: dict) -> list[dict]:
    """One ESPN scoreboard week -> the rows travel needs, nothing else."""
    week = (payload.get("week") or {}).get("number")
    rows = []
    for event in payload.get("events") or []:
        comp = (event.get("competitions") or [{}])[0]
        sides = {
            c.get("homeAway"): (c.get("team") or {}).get("abbreviation")
            for c in comp.get("competitors") or []
        }
        if not sides.get("home") or not sides.get("away"):
            continue
        venue = comp.get("venue") or {}
        address = venue.get("address") or {}
        rows.append(
            {
                "week": week,
                "kickoff": event.get("date") or "",
                "away": sides["away"],
                "home": sides["home"],
                "neutral": bool(comp.get("neutralSite")),
                "venue": venue.get("fullName") or "",
                "city": address.get("city") or "",
                "state": address.get("state") or "",
                "country": address.get("country") or "",
                "indoor": bool(venue.get("indoor")),
            }
        )
    return rows


async def fetch_week(week: int, client: httpx.AsyncClient | None = None) -> list[dict]:
    """One regular-season week. Raises on failure, so the runner leaves the
    week unfetched and tries again next run."""
    own = client is None
    client = client or httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": "FBBible/1.0 (personal draft tool, hourly)"},
    )
    try:
        response = await client.get(
            URL, params={"seasontype": SEASON_TYPE, "week": week, "dates": config.SEASON_YEAR}
        )
        response.raise_for_status()
        return reduce_week(response.json())
    finally:
        if own:
            await client.aclose()


_TEXT = ("kickoff", "away", "home", "venue", "city", "state", "country")


def clean_row(row: object) -> dict | None:
    """Rebuilt field by field at the door: this is rendered into the page."""
    if not isinstance(row, dict):
        return None
    out = {k: str(row.get(k) or "")[:80] for k in _TEXT}
    if out["away"] not in STADIUMS or out["home"] not in STADIUMS or not _when(out["kickoff"]):
        return None
    out["neutral"] = bool(row.get("neutral"))
    out["indoor"] = bool(row.get("indoor"))
    return out


def merge(state: dict | None, weeks: dict, now: datetime) -> dict:
    """Replace each pushed week whole -- a flexed game moves, it is not added."""
    state = {
        "weeks": dict((state or {}).get("weeks") or {}),
        "fetched": dict((state or {}).get("fetched") or {}),
    }
    for key, rows in (weeks or {}).items():
        try:
            week = int(key)
        except (TypeError, ValueError):
            continue
        if week not in WEEKS or not isinstance(rows, list):
            continue
        cleaned = [{**r, "week": week} for r in (clean_row(r) for r in rows[:20]) if r]
        if not cleaned:
            continue  # an empty answer is a failed fetch, not an empty week
        state["weeks"][str(week)] = cleaned
        state["fetched"][str(week)] = now.isoformat()
    return state


def known(state: dict | None) -> dict[str, str]:
    """{week: fetched_at} -- so the runner fetches each week once."""
    return dict((state or {}).get("fetched") or {})


def to_fetch(state: dict | None, slate_week: int | None) -> list[int]:
    """The current and next week every run (kickoffs flex), then every week
    never fetched, capped per run."""
    have = known(state)
    todo = [w for w in (slate_week, (slate_week or 0) + 1) if w in WEEKS]
    todo += [w for w in WEEKS if str(w) not in have and w not in todo]
    return todo[:MAX_WEEKS_PER_RUN]


# --- the measurements -------------------------------------------------------


def _site(row: dict) -> tuple[float, float, str] | None:
    """Where the game is played, or None for a neutral city not mapped."""
    away_from_home = row["neutral"] or (row["country"] and row["country"] != "USA")
    if not away_from_home:
        return STADIUMS[row["home"]]
    return NEUTRAL_CITIES.get(_norm(row["city"]))


def _games(state: dict | None, code: str) -> list[dict]:
    out = []
    for rows in ((state or {}).get("weeks") or {}).values():
        for row in rows:
            if code not in (row["away"], row["home"]):
                continue
            at_home = row["home"] == code and not (
                row["neutral"] or (row["country"] and row["country"] != "USA")
            )
            out.append(
                {
                    "week": row.get("week"),
                    "when": _when(row["kickoff"]),
                    "opp": row["home"] if row["away"] == code else row["away"],
                    "where": "home" if at_home else ("neutral" if row["neutral"] else "away"),
                    "site": None if at_home else _site(row),
                    "city": row["city"],
                    "key": f"{row['away']} @ {row['home']}",
                }
            )
    out = [g for g in out if g["when"]]
    out.sort(key=lambda g: g["when"])
    return out


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _offset_hours(zone: str, at: datetime) -> float:
    return at.astimezone(ZoneInfo(zone)).utcoffset().total_seconds() / 3600


def team_read(state: dict | None, code: str, now: datetime) -> dict | None:
    """The team's next game (or the one in progress), with what it took to
    get there. None when the schedule holds no game ahead for it."""
    games = _games(state, code)
    # A game stays "next" until four hours after kickoff, so the read does
    # not flip to next week while it is being played.
    idx = next((i for i, g in enumerate(games) if g["when"] > now - timedelta(hours=4)), None)
    if idx is None or code not in STADIUMS:
        return None
    home = STADIUMS[code]
    game = games[idx]
    window = games[max(0, idx - WINDOW + 1) : idx + 1]
    unmapped = [g for g in window if g["where"] != "home" and g["site"] is None]

    def trip(g: dict) -> float:
        return 0.0 if g["where"] == "home" else _miles(home, g["site"])

    this_trip = None if game in unmapped else round(trip(game))
    window_miles = None
    if not unmapped:
        # Earlier road games are round trips; this one is outbound only.
        window_miles = round(sum(2 * trip(g) for g in window[:-1]) + trip(game))
    streak = 0
    for g in reversed(games[: idx + 1]):
        if (g["where"] == "home") != (game["where"] == "home"):
            break
        streak += 1
    prev = games[idx - 1] if idx else None
    rest = None
    if prev:
        rest = (
            game["when"].astimezone(CENTRAL).date() - prev["when"].astimezone(CENTRAL).date()
        ).days
    span = None
    if len(window) == WINDOW:
        span = (
            game["when"].astimezone(CENTRAL).date() - window[0]["when"].astimezone(CENTRAL).date()
        ).days
    zones = 0.0
    body_clock = ""
    if game["site"]:
        zones = _offset_hours(game["site"][2], game["when"]) - _offset_hours(home[2], game["when"])
        local = game["when"].astimezone(ZoneInfo(game["site"][2]))
        if zones >= BODY_CLOCK_ZONES and local.hour < EARLY_LOCAL_HOUR:
            clock = game["when"].astimezone(ZoneInfo(home[2]))
            body_clock = f"{clock.hour % 12 or 12}:{clock:%M} {'AM' if clock.hour < 12 else 'PM'}"
    read = {
        "code": code,
        "game": game["key"],
        "week": game["week"],
        "opp": game["opp"],
        "where": game["where"],
        "city": game["city"] if game["where"] != "home" else "",
        "trip_miles": this_trip,
        "window_miles": window_miles,
        "window_games": len(window),
        "streak": streak,
        "rest_days": rest,
        "bye": rest is not None and rest >= BYE_DAYS,
        "span_days": span,
        "zones": round(zones),
        "body_clock": body_clock,
    }
    read["line"] = _line(read)
    return read


def _line(r: dict) -> str:
    at = {"home": "vs", "away": "at", "neutral": "vs"}[r["where"]]
    bits = [
        f"Wk {r['week']} {at} {r['opp']}" + (f" in {r['city']}" if r["where"] == "neutral" else "")
    ]
    place = "home" if r["where"] == "home" else "road"
    if r["streak"] >= 2:
        bits.append(f"{_ordinal(r['streak'])} straight {place} game")
    if r["where"] != "home":
        bits.append(
            f"~{r['trip_miles']:,} mi this trip"
            if r["trip_miles"] is not None
            else f"neutral site in {r['city'] or 'an unlisted city'} — distance not mapped"
        )
    if r["window_miles"] is not None and r["window_games"] > 1:
        bits.append(f"~{r['window_miles']:,} mi over the last {r['window_games']} games")
    if r["span_days"] is not None:
        bits.append(f"{r['window_games']} games in {r['span_days']} days")
    if r["bye"]:
        bits.append("off a bye")
    elif r["rest_days"] is not None:
        bits.append(f"{r['rest_days']} days rest")
    if r["zones"]:
        n = abs(r["zones"])
        bits.append(f"{n} time zone{'s' if n != 1 else ''} {'east' if r['zones'] > 0 else 'west'}")
    if r["body_clock"]:
        bits.append(f"body clock {r['body_clock']} at kickoff")
    return " · ".join(bits)


def edge(a: dict, b: dict) -> list[str]:
    """Which side the written rules favour, and why -- empty when no gap
    clears a rule. `a` and `b` are the two teams' reads for the same game."""
    reasons: list[tuple[str, str]] = []
    for x, y in ((a, b), (b, a)):
        if x["rest_days"] is not None and y["rest_days"] is not None:
            if x["rest_days"] - y["rest_days"] >= REST_EDGE_DAYS:
                reasons.append(
                    (
                        x["code"],
                        f"{x['code']} rested {x['rest_days']} days "
                        f"to {y['code']}'s {y['rest_days']}",
                    )
                )
        if y["where"] != "home" and y["streak"] >= ROAD_STREAK and x["where"] == "home":
            reasons.append(
                (x["code"], f"{y['code']} on its {_ordinal(y['streak'])} straight road game")
            )
        if x["window_miles"] is not None and y["window_miles"] is not None:
            gap = y["window_miles"] - x["window_miles"]
            if gap >= MILES_EDGE:
                reasons.append(
                    (x["code"], f"{y['code']} flew ~{gap:,} more miles over the last 3 games")
                )
        if y["body_clock"]:
            reasons.append(
                (x["code"], f"{y['code']}'s body clock reads {y['body_clock']} at kickoff")
            )
    if not reasons:
        return []
    sides = {code for code, _ in reasons}
    head = (
        f"Travel edge (rule): {next(iter(sides))}"
        if len(sides) == 1
        else "Travel (rule): both sides"
    )
    return [head + " — " + "; ".join(text for _, text in reasons)]


def reads(state: dict | None, now: datetime | None = None) -> dict | None:
    """{"teams": {code: read}, "games": {"AWY @ HOM": [edge]}, "as_of"} or
    None until the runner has pushed a schedule."""
    if not (state or {}).get("weeks"):
        return None
    now = now or datetime.now(UTC)
    teams = {code: r for code in STADIUMS if (r := team_read(state, code, now))}
    games: dict[str, list[str]] = {}
    for r in teams.values():
        away_code, home_code = r["game"].split(" @ ")
        away, home = teams.get(away_code), teams.get(home_code)
        if away and home and away["game"] == home["game"] == r["game"]:
            games[r["game"]] = edge(away, home)
    fetched = sorted(known(state).values())
    return {
        "teams": teams,
        "games": games,
        "as_of": fetched[-1][:10] if fetched else "",
        "source": "ESPN schedule",
    }
