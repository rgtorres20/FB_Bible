"""NBA FFBets: points, rebounds and assists, game by game.

Owner, Oct 23: "I want to add a nba section focus on points assist and
rebounds". Same panel as the NFL and college games, same honesty rules.

Every shape below was probed live from the Actions runner first (probe
runs Oct 23 -- ESPN 403s this sandbox and Vercel, as it does for the
football feeds):

- scoreboard: `day.date`, `season.year` (2027 for 2026-27), each event's
  competitors and `odds[0].details` / `overUnder` (DraftKings) -- which a
  finished game no longer carries, so the slate keeps whatever it saw.
- summary: `boxscore.players[2]`, each with `team.abbreviation` and one
  statistics block whose labels are MIN, PTS, FG, 3PT, FT, REB, AST, TO,
  STL, BLK, OREB, DREB, PF, +/-; each athlete carries `athlete.id`,
  `starter`, `didNotPlay` and `stats` as strings.
- athlete gamelog (`site.web.api.espn.com/.../athletes/{id}/gamelog`):
  labels MIN, FG, FG%, 3PT, 3P%, FT, FT%, REB, AST, BLK, STL, PF, TO, PTS;
  `seasonTypes` lists the postseason FIRST, then the regular season, each
  split by month into `categories[].events[] = {eventId, stats}`, and
  `events[eventId]` carries `opponent.abbreviation`, `gameDate`, `atVs`.
- injuries: one entry per team, each with `injuries[] = {athlete
  {displayName, links}, status ("Out", "Day-To-Day"), shortComment}`; the
  athlete id lives in the links (`/id/4712863/`).

There is no free NBA projection, so nothing here is one. Every number is a
real game: this season's from box scores (fetched once each), last
season's from each slate player's ESPN game log (regular season only,
fetched once -- it is final). The panel shows both averages side by side
and counts how many real games cleared a typed line; it never blends them
into an invented forecast.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from . import vegas

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
INJURIES = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
GAMELOG = (
    "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{aid}/gamelog"
)

CENTRAL = ZoneInfo("America/Chicago")
# 2 (Oct 23): v1 stored 50 preseason box scores on its first live run;
# bumping discards them and the runner rebuilds the season cleanly.
VERSION = 2
STATS = ("min", "pts", "reb", "ast")
_BOX_LABELS = {"MIN": "min", "PTS": "pts", "REB": "reb", "AST": "ast"}

# Chosen, not measured -- docs/ASSUMPTIONS.md says what moves if wrong.
MIN_MINUTES = 15.0  # a rotation player: averages this many minutes this season
PER_TEAM = 8  # most rotation players shown per side
RECENT = 5  # games in the "last 5" line
LOOKBACK_DAYS = 14  # first run with nothing stored: scan this far back for finals
LOOKAHEAD_DAYS = 7  # once today is final, how far ahead to look for the next game day
MAX_DAYS_PER_RUN = 10
MAX_BOXES_PER_RUN = 60
MAX_LOGS_PER_RUN = 60
OUT = ("Out",)  # statuses that take a player off every market


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=60.0,
        follow_redirects=True,
        headers={"User-Agent": "FBBible/1.0 (personal fantasy tool, hourly)"},
    )


async def _get(http: httpx.AsyncClient, url: str, params: dict | None = None) -> dict:
    resp = await http.get(url, params=params or {})
    resp.raise_for_status()
    return resp.json()


async def fetch_scoreboard(http: httpx.AsyncClient, day: str | None = None) -> dict:
    """The default board (ESPN's current day) or one day, as YYYY-MM-DD."""
    return await _get(http, SCOREBOARD, {"dates": day.replace("-", "")} if day else None)


async def fetch_summary(http: httpx.AsyncClient, event_id: str) -> dict:
    return await _get(http, SUMMARY, {"event": event_id})


async def fetch_injuries(http: httpx.AsyncClient) -> dict:
    return await _get(http, INJURIES)


async def fetch_gamelog(http: httpx.AsyncClient, aid: str, season: int) -> dict:
    return await _get(http, GAMELOG.format(aid=aid), {"season": str(season)})


# --- the slate ----------------------------------------------------------------


def _competition(event: dict) -> dict:
    return (event.get("competitions") or [{}])[0]


def _state(event: dict) -> str:
    status = _competition(event).get("status") or event.get("status") or {}
    return str(((status.get("type") or {}).get("state")) or "")


def board_day(payload: dict) -> str:
    return str((payload.get("day") or {}).get("date") or "")[:10]


def season_year(payload: dict) -> int | None:
    year = (payload.get("season") or {}).get("year")
    return year if isinstance(year, int) else None


def _season_type(event: dict) -> int | None:
    kind = (event.get("season") or {}).get("type")
    return kind if isinstance(kind, int) else None


def counted(payload: dict) -> list[dict]:
    """The events that are this season's sample: everything but the
    preseason. ESPN marks the season on each EVENT (`season.type`, 1 =
    preseason) -- a board fetched for a date carries no top-level season
    at all, which is how the first live run stored 50 exhibition games
    (Oct 23, probed after)."""
    return [e for e in payload.get("events") or [] if _season_type(e) != 1]


def all_final(payload: dict) -> bool:
    """Every game on the board is over: the reader is looking at tomorrow."""
    events = payload.get("events") or []
    return bool(events) and all(_state(e) == "post" for e in events)


def next_day(day: str) -> str:
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def slate(payload: dict, now: datetime | None = None) -> dict:
    """The day's games in the NFL slate's row shape, plus each game's ESPN
    event id and state."""
    rows = vegas.build_rows(payload)
    by_game = {}
    for event in payload.get("events") or []:
        sides = {
            c.get("homeAway"): (c.get("team") or {}).get("abbreviation", "?")
            for c in _competition(event).get("competitors") or []
        }
        by_game[f"{sides.get('away')} @ {sides.get('home')}"] = event
    games = []
    for row in rows:
        event = by_game.get(row["game"])
        if event:
            games.append({**row, "event_id": str(event.get("id")), "state": _state(event)})
    return {
        "day": board_day(payload),
        "season": season_year(payload),
        "fetched_at": (now or datetime.now(UTC)).isoformat(),
        "games": games,
    }


def finals(payload: dict) -> list[str]:
    """Finished games that count -- the preseason never does."""
    return [str(e.get("id")) for e in counted(payload) if _state(e) == "post"]


# --- box scores ---------------------------------------------------------------


def _num(text: object) -> float | None:
    try:
        return float(str(text).replace(",", "").lstrip("+"))
    except ValueError:
        return None


def _central_day(iso: str) -> str:
    try:
        stamp = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return ""
    return stamp.astimezone(CENTRAL).date().isoformat()


def reduce_box(summary: dict, event_id: str) -> dict | None:
    """{"id", "day", "teams": {abbr: opponent}, "players": {athlete id:
    {"name", "team", "opp", "pos", min, pts, reb, ast}}}. A player marked
    didNotPlay, or with no minutes, played no game and is left out -- a
    DNP is not a zero-point game. None when the summary carries no box."""
    header = summary.get("header") or {}
    when = ""
    for comp in header.get("competitions") or []:
        when = comp.get("date") or when
    sides = (summary.get("boxscore") or {}).get("players") or []
    abbrs = [((s.get("team") or {}).get("abbreviation") or "") for s in sides]
    if len(sides) != 2 or not all(abbrs):
        return None
    teams = {abbrs[0]: abbrs[1], abbrs[1]: abbrs[0]}
    players: dict[str, dict] = {}
    for side, abbr in zip(sides, abbrs, strict=True):
        for block in side.get("statistics") or []:
            columns = [_BOX_LABELS.get(label) for label in block.get("labels") or []]
            for entry in block.get("athletes") or []:
                athlete = entry.get("athlete") or {}
                aid = str(athlete.get("id") or "")
                if not aid or entry.get("didNotPlay"):
                    continue
                row: dict = {
                    "name": athlete.get("displayName") or "",
                    "team": abbr,
                    "opp": teams[abbr],
                    "pos": (athlete.get("position") or {}).get("abbreviation") or "",
                }
                for field, value in zip(columns, entry.get("stats") or [], strict=False):
                    number = _num(value) if field else None
                    if field and number is not None:
                        row[field] = number
                if row.get("min"):
                    players[aid] = row
    return {"id": str(event_id), "day": _central_day(when), "teams": teams, "players": players}


# --- last season's game log ---------------------------------------------------

_LOG_LABELS = {"MIN": "min", "PTS": "pts", "REB": "reb", "AST": "ast"}


def reduce_gamelog(payload: dict) -> list[list]:
    """[[day, opponent, min, pts, reb, ast], ...] in date order, regular
    season only -- ESPN lists the postseason first, and a playoff series
    against one opponent is not the sample a regular-season line is set
    against."""
    labels = payload.get("labels") or []
    idx = {_LOG_LABELS[label]: i for i, label in enumerate(labels) if label in _LOG_LABELS}
    if len(idx) != len(_LOG_LABELS):
        return []
    meta = payload.get("events") or {}
    rows = []
    for season_type in payload.get("seasonTypes") or []:
        if "regular" not in str(season_type.get("displayName") or "").lower():
            continue
        for category in season_type.get("categories") or []:
            for event in category.get("events") or []:
                stats = event.get("stats") or []
                info = meta.get(str(event.get("eventId"))) or {}
                values = [_num(stats[idx[k]]) if idx[k] < len(stats) else None for k in STATS]
                if any(v is None for v in values) or not values[0]:
                    continue
                rows.append(
                    [
                        _central_day(info.get("gameDate") or ""),
                        str((info.get("opponent") or {}).get("abbreviation") or "")[:6],
                        *values,
                    ]
                )
    rows.sort(key=lambda r: r[0])
    return rows


# --- injuries -----------------------------------------------------------------

_ATHLETE_ID = re.compile(r"/id/(\d+)")


def _athlete_id(athlete: dict) -> str:
    if athlete.get("id"):
        return str(athlete["id"])
    for link in athlete.get("links") or []:
        match = _ATHLETE_ID.search(str(link.get("href") or ""))
        if match:
            return match.group(1)
    return ""


def reduce_injuries(payload: dict) -> dict[str, dict]:
    """{athlete id: {"name", "team_name", "status", "note"}} for every
    listed player. The feed groups by team display name ("Atlanta Hawks"),
    which is also what the slate rows carry -- so a player listed out who
    has not played this season still lands on his game's report."""
    out = {}
    for team in payload.get("injuries") or []:
        team_name = team.get("displayName") or ""
        for item in team.get("injuries") or []:
            athlete = item.get("athlete") or {}
            aid = _athlete_id(athlete)
            if not aid:
                continue
            out[aid] = {
                "name": athlete.get("displayName") or "",
                "team_name": team_name,
                "status": item.get("status") or "",
                "note": item.get("shortComment") or "",
            }
    return out


# --- the stored season --------------------------------------------------------


def blank() -> dict:
    return {"v": VERSION, "slate": {}, "boxes": {}, "last": {}, "injuries": {}, "through": ""}


def current(state: dict | None) -> dict:
    if not state or state.get("v") != VERSION:
        return blank()
    return state


_SLATE_FIELDS = (
    "game",
    "fav",
    "total",
    "imp",
    "kickoff",
    "away_name",
    "home_name",
    "tv",
    "event_id",
    "state",
)


def clean_slate(raw: dict | None) -> dict:
    """Rebuilt field by field: this renders into the page."""
    games = []
    for row in ((raw or {}).get("games") or [])[:20]:
        if isinstance(row, dict) and row.get("game"):
            games.append({f: str(row.get(f) or "")[:80] for f in _SLATE_FIELDS})
    season = (raw or {}).get("season")
    return {
        "day": str((raw or {}).get("day") or "")[:10],
        "season": season if isinstance(season, int) else None,
        "fetched_at": str((raw or {}).get("fetched_at") or "")[:40],
        "games": games,
    }


def clean_box(raw: dict | None) -> dict | None:
    if not isinstance(raw, dict) or not raw.get("id"):
        return None
    teams = {str(k)[:6]: str(v)[:6] for k, v in (raw.get("teams") or {}).items()}
    if len(teams) != 2:
        return None
    players = {}
    for aid, p in (raw.get("players") or {}).items():
        if not isinstance(p, dict) or p.get("team") not in teams:
            continue
        row = {
            "name": str(p.get("name") or "")[:60],
            "team": p["team"],
            "opp": teams[p["team"]],
            "pos": str(p.get("pos") or "")[:4],
        }
        for stat in STATS:
            v = p.get(stat)
            if isinstance(v, int | float) and 0 <= v <= 200:
                row[stat] = float(v)
        if row.get("min"):
            players[str(aid)[:20]] = row
    return {
        "id": str(raw["id"])[:20],
        "day": str(raw.get("day") or "")[:10],
        "teams": teams,
        "players": players,
    }


def clean_log(rows: object) -> list[list]:
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not (isinstance(r, list) and len(r) == 6):
            continue
        nums = r[2:]
        if not all(isinstance(v, int | float) and 0 <= v <= 200 for v in nums):
            continue
        out.append([str(r[0])[:10], str(r[1])[:6], *[float(v) for v in nums]])
    return out[:120]


def clean_injuries(raw: dict | None) -> dict[str, dict]:
    out = {}
    for aid, item in (raw or {}).items():
        if isinstance(item, dict) and str(aid).isdigit():
            out[str(aid)[:20]] = {
                "name": str(item.get("name") or "")[:60],
                "team_name": str(item.get("team_name") or "")[:60],
                "status": str(item.get("status") or "")[:30],
                "note": str(item.get("note") or "")[:200],
            }
    return out


def merge(
    state: dict | None,
    slate_raw: dict | None = None,
    boxes: list | None = None,
    last: dict | None = None,
    injuries: dict | None = None,
    through: str = "",
    now: datetime | None = None,
) -> dict:
    """The new slate replaces the old; boxes add by event id and logs by
    athlete, so a re-push replaces itself rather than counting twice. An
    empty injury report is kept only when ESPN really answered -- the
    runner sends None when the fetch failed, and the old list stands."""
    state = dict(current(state))
    new_slate = clean_slate(slate_raw)
    if new_slate["games"]:
        state["slate"] = new_slate
    stored = dict(state.get("boxes") or {})
    for raw in boxes or []:
        box = clean_box(raw)
        if box:
            stored[box["id"]] = box
    state["boxes"] = stored
    logs = dict(state.get("last") or {})
    for aid, rows in (last or {}).items():
        if str(aid).isdigit():
            logs[str(aid)[:20]] = clean_log(rows)
    state["last"] = logs
    if injuries is not None:
        state["injuries"] = {
            "fetched_at": (now or datetime.now(UTC)).isoformat(),
            "players": clean_injuries(injuries),
        }
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", through or "") and through > (state.get("through") or ""):
        state["through"] = through
    return state


# --- this season, per player --------------------------------------------------


def season_games(state: dict | None) -> dict[str, dict]:
    """{athlete id: {"name", "team", "pos", "games": [[day, opp, min, pts,
    reb, ast], ...]}} from every stored box, in date order. The team is the
    one he played for most recently, so a traded player sits with his new
    side."""
    players: dict[str, dict] = {}
    boxes = sorted((current(state).get("boxes") or {}).values(), key=lambda b: b.get("day") or "")
    for box in boxes:
        for aid, p in (box.get("players") or {}).items():
            row = players.setdefault(aid, {"name": p["name"], "pos": p.get("pos", ""), "games": []})
            row["team"] = p["team"]
            row["name"] = p["name"] or row["name"]
            row["games"].append(
                [box.get("day") or "", p["opp"], *[float(p.get(s) or 0) for s in STATS]]
            )
    return players


def _avg(games: list[list]) -> dict | None:
    if not games:
        return None
    n = len(games)
    out = {"n": n}
    for i, stat in enumerate(STATS):
        out[stat] = round(sum(g[2 + i] for g in games) / n, 1)
    out["pra"] = round(out["pts"] + out["reb"] + out["ast"], 1)
    return out


def rotation(state: dict | None, teams: set[str]) -> dict[str, list[str]]:
    """{team: [athlete ids]} -- this season's rotation players on these
    teams (MIN_MINUTES a game or more), most minutes first."""
    out: dict[str, list[tuple[float, str]]] = {}
    for aid, p in season_games(state).items():
        if p["team"] not in teams:
            continue
        minutes = sum(g[2] for g in p["games"]) / len(p["games"])
        if minutes >= MIN_MINUTES:
            out.setdefault(p["team"], []).append((minutes, aid))
    return {t: [aid for _, aid in sorted(rows, reverse=True)] for t, rows in out.items()}


def slate_teams(state: dict | None) -> set[str]:
    teams = set()
    for g in (current(state).get("slate") or {}).get("games") or []:
        codes = vegas.matchup_teams(g.get("game"))
        if codes:
            teams.update(codes)
    return teams


def known(state: dict | None) -> dict:
    """What the runner needs to fetch only what is missing: the box scores
    held, the last day fully scanned, and the slate's rotation players who
    have no last-season log yet (an empty log is a fetched rookie)."""
    st = current(state)
    logs = st.get("last") or {}
    need = [
        aid
        for team_ids in rotation(st, slate_teams(st)).values()
        for aid in team_ids[:PER_TEAM]
        if aid not in logs
    ]
    return {
        "events": sorted((st.get("boxes") or {}).keys()),
        "through": st.get("through") or "",
        "need_last": need,
        "season": (st.get("slate") or {}).get("season"),
    }


def allowed(state: dict | None) -> dict[str, dict]:
    """{team: {"n": games, stat: [per game, rank from the most, of]}} --
    what each defense has given up to opponents this season, from box
    scores. Competition ranking, so a tie is never dressed up as order."""
    totals: dict[str, dict[str, float]] = {}
    games: dict[str, int] = {}
    for box in (current(state).get("boxes") or {}).values():
        sums: dict[str, dict[str, float]] = {}
        for p in (box.get("players") or {}).values():
            bucket = sums.setdefault(p["team"], {"pts": 0.0, "reb": 0.0, "ast": 0.0})
            for stat in bucket:
                bucket[stat] += float(p.get(stat) or 0)
        for team, opp in (box.get("teams") or {}).items():
            if team not in sums:
                continue
            games[opp] = games.get(opp, 0) + 1
            t = totals.setdefault(opp, {"pts": 0.0, "reb": 0.0, "ast": 0.0})
            for stat, v in sums[team].items():
                t[stat] += v
    per = {t: {s: round(v / games[t], 1) for s, v in sums.items()} for t, sums in totals.items()}
    out: dict[str, dict] = {t: {"n": games[t]} for t in per}
    for stat in ("pts", "reb", "ast"):
        values = [per[t][stat] for t in per]
        for t in per:
            v = per[t][stat]
            out[t][stat] = [v, 1 + sum(1 for x in values if x > v), len(values)]
    return out


# --- the panel ----------------------------------------------------------------


def _season_label(year: int | None) -> tuple[str, str]:
    if not year:
        return "this season", "last season"
    return f"{year - 1}-{str(year)[2:]}", f"{year - 2}-{str(year - 1)[2:]}"


def _tip(iso: str) -> str:
    try:
        stamp = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(CENTRAL)
    except ValueError:
        return ""
    hour = stamp.hour % 12 or 12
    return f"{stamp:%a} {hour}:{stamp:%M} {'AM' if stamp.hour < 12 else 'PM'} CT"


def _stamp(iso: str) -> str:
    try:
        stamp = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(CENTRAL)
    except ValueError:
        return ""
    hour = stamp.hour % 12 or 12
    return f"{stamp:%a %b} {stamp.day} {hour}:{stamp:%M} {'AM' if stamp.hour < 12 else 'PM'}"


def _day_label(day: str) -> str:
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return day
    return f"{d:%a %b} {d.day}"


def _short_day(day: str) -> str:
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return day
    return f"{d.month}/{d.day}"


def stack(state: dict | None) -> dict | None:
    """The day's slate in the shape the FFBets panel's NBA side draws, or
    None until a slate has been pushed."""
    st = current(state)
    slate_state = st.get("slate") or {}
    rows = slate_state.get("games") or []
    if not rows:
        return None
    this_label, last_label = _season_label(slate_state.get("season"))
    players = season_games(st)
    logs = st.get("last") or {}
    hurt = (st.get("injuries") or {}).get("players") or {}
    defense = allowed(st)
    teams = slate_teams(st)
    rota = rotation(st, teams)
    games, uncovered = [], []
    for row in rows:
        codes = vegas.matchup_teams(row.get("game"))
        if not codes:
            continue
        away, home = codes
        sides: dict[str, list] = {}
        names = {away: row.get("away_name") or "", home: row.get("home_name") or ""}
        report = [
            {
                "name": item["name"],
                "team": team,
                "status": item["status"],
                "note": item.get("note") or "",
            }
            for team in codes
            for item in hurt.values()
            if names[team] and item.get("team_name") == names[team]
        ]
        report.sort(key=lambda r: (r["status"] not in OUT, r["team"], r["name"]))
        for team in codes:
            shown = []
            for aid in rota.get(team, []):
                status = (hurt.get(aid) or {}).get("status") or ""
                if status in OUT or len(shown) >= PER_TEAM:
                    continue
                p = players[aid]
                last = logs.get(aid) or []
                recent_src = p["games"] if p["games"] else last
                shown.append(
                    {
                        "id": aid,
                        "name": p["name"],
                        "team": team,
                        "pos": p.get("pos") or "",
                        "status": status,
                        "note": (hurt.get(aid) or {}).get("note", "") if status else "",
                        "this": _avg(p["games"]),
                        "last": _avg(last),
                        # Per game [pts, reb, ast], for counting a typed line.
                        "g": {
                            "this": [[g[3], g[4], g[5]] for g in p["games"]],
                            "last": [[g[3], g[4], g[5]] for g in last],
                        },
                        "recent": [
                            [_short_day(g[0]), g[1], g[3], g[4], g[5], g[2]]
                            for g in recent_src[-RECENT:]
                        ][::-1],
                        "recent_season": this_label if p["games"] else last_label,
                    }
                )
            sides[team] = shown
        if not any(sides.values()):
            uncovered.append(row.get("game") or "")
        games.append(
            {
                "game": row.get("game"),
                "away": away,
                "home": home,
                "away_name": row.get("away_name") or away,
                "home_name": row.get("home_name") or home,
                "tip": _tip(row.get("kickoff") or ""),
                "tip_iso": row.get("kickoff") or "",
                "state": row.get("state") or "",
                "tv": row.get("tv") or "",
                "fav": row.get("fav") if row.get("fav") not in ("", "—") else "",
                "total": row.get("total") if row.get("total") not in ("", "—") else "",
                "players": sides,
                "injuries": report,
                "allowed": {t: defense[t] for t in codes if t in defense},
            }
        )
    games.sort(key=lambda g: g["tip_iso"])
    fetched = slate_state.get("fetched_at") or ""
    injuries_at = (st.get("injuries") or {}).get("fetched_at") or ""
    return {
        "league": "nba",
        "day": slate_state.get("day") or "",
        "day_label": _day_label(slate_state.get("day") or ""),
        "this_label": this_label,
        "last_label": last_label,
        "source": "ESPN box scores and game logs · real averages, not projections",
        "fetched_at": fetched,
        "as_of": _stamp(fetched),
        "injuries_as_of": _stamp(injuries_at),
        "boxes": len(st.get("boxes") or {}),
        "games": games,
        "uncovered": uncovered,
    }
