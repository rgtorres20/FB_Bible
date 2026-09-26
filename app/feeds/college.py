"""College FFBets: the week's top-25 games and every player's real box scores.

Owner, Sep 26: "another section that looks at college games too just like
nfl -- let's keep to top 25 games". The NFL side leans on Rotowire's weekly
forecast via Sleeper; there is no free college equivalent, so this section
is built from what can be measured instead: ESPN's scoreboard (rankings,
lines, kickoffs) and ESPN's per-game box scores (every player's passing,
rushing and receiving line). A player's number on the market tabs is his
**season average**, never a projection, and the page says so.

Probed live before a line was written (probe runs 41-51, 2026-09-26):

- ESPN 403s urllib's client and passes httpx with the same honest UA, so
  the runner fetches with httpx (as push_vegas does) and pushes here;
  Vercel's IPs are blocked outright, same as the NFL slate.
- The FBS scoreboard (`groups=80`) takes `week=`; every competitor carries
  `curatedRank.current` (99 when unranked), and `odds` rides only some
  games -- 14 of 71 and 14 of 59 in the weeks probed -- so a game with no
  line is common and shown as such.
- The same event shape the NFL slate parser reads, so `vegas.build_rows`
  shapes these rows too: one odds parser, not two.
- A game's `summary` carries `boxscore.players[]`, one entry per team with
  its `team.abbreviation`, and `statistics[]` categories named `passing`,
  `rushing`, `receiving`, each with `keys`, `labels` and one `stats` array
  per athlete (passing labels C/ATT, YDS, AVG, TD, INT; rushing and
  receiving rows read count, yards, average, TD, long).
- No position is published in the box score. A player's role is read from
  what he did -- passer, rusher or receiver -- and labelled as such.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from . import vegas

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary"
FBS = "80"
TOP = 25
SEASON = 2026
# Box scores fetched per runner push. One summary is ~500KB; the first run
# of a season has every ranked team's played games to catch up on, and a
# runner step that runs for minutes is a step that times out.
MAX_BOXES_PER_RUN = 60
VERSION = 1

# Box-score columns kept, by category, keyed on ESPN's stat keys with the
# printed label as the fallback (passing keys verified; rushing and
# receiving read in the same shape -- see the module docstring).
_CATEGORIES = {
    "passing": {
        "completions/passingAttempts": "cmp_att",
        "C/ATT": "cmp_att",
        "passingYards": "pass_yd",
        "passingTouchdowns": "pass_td",
        "interceptions": "pass_int",
        "INT": "pass_int",
    },
    "rushing": {
        "rushingAttempts": "rush_att",
        "CAR": "rush_att",
        "rushingYards": "rush_yd",
        "rushingTouchdowns": "rush_td",
    },
    "receiving": {
        "receptions": "rec",
        "REC": "rec",
        "receivingYards": "rec_yd",
        "receivingTouchdowns": "rec_td",
    },
}
# Labels shared by several categories, read by category.
_SHARED_LABELS = {
    "passing": {"YDS": "pass_yd", "TD": "pass_td"},
    "rushing": {"YDS": "rush_yd", "TD": "rush_td"},
    "receiving": {"YDS": "rec_yd", "TD": "rec_td"},
}
STATS = (
    "pass_cmp",
    "pass_att",
    "pass_yd",
    "pass_td",
    "pass_int",
    "rush_att",
    "rush_yd",
    "rush_td",
    "rec",
    "rec_yd",
    "rec_td",
)


# --- runner side: fetch -------------------------------------------------------


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=60.0,
        follow_redirects=True,
        headers={"User-Agent": "FBBible/1.0 (personal fantasy tool, hourly)"},
    )


async def fetch_scoreboard(http: httpx.AsyncClient, week: int | None = None) -> dict:
    params = {"groups": FBS}
    if week:
        params["week"] = str(week)
    resp = await http.get(SCOREBOARD, params=params)
    resp.raise_for_status()
    return resp.json()


async def fetch_summary(http: httpx.AsyncClient, event_id: str) -> dict:
    resp = await http.get(SUMMARY, params={"event": event_id})
    resp.raise_for_status()
    return resp.json()


# --- the slate ----------------------------------------------------------------


def _competition(event: dict) -> dict:
    return (event.get("competitions") or [{}])[0]


def _state(event: dict) -> str:
    """'pre', 'in' or 'post', as ESPN states it."""
    status = _competition(event).get("status") or event.get("status") or {}
    return str(((status.get("type") or {}).get("state")) or "")


def ranks(event: dict) -> dict[str, int]:
    """{team abbreviation: AP-style rank} for ranked competitors only."""
    out = {}
    for c in _competition(event).get("competitors") or []:
        rank = ((c.get("curatedRank") or {}).get("current")) or 99
        abbr = (c.get("team") or {}).get("abbreviation") or ""
        if abbr and isinstance(rank, int) and rank <= TOP:
            out[abbr] = rank
    return out


def top25(payload: dict) -> list[dict]:
    return [e for e in payload.get("events") or [] if ranks(e)]


def week_number(payload: dict) -> int | None:
    n = (payload.get("week") or {}).get("number")
    return int(n) if isinstance(n, int) else None


def slate(payload: dict, now: datetime | None = None) -> dict:
    """The week's top-25 games in the NFL slate's row shape, plus each
    game's ranks, ESPN event id and state."""
    events = top25(payload)
    rows = vegas.build_rows({"events": events})
    by_game = {}
    for event in events:
        sides = {
            c.get("homeAway"): (c.get("team") or {}).get("abbreviation", "?")
            for c in _competition(event).get("competitors") or []
        }
        by_game[f"{sides.get('away')} @ {sides.get('home')}"] = event
    games = []
    for row in rows:
        event = by_game.get(row["game"])
        if not event:
            continue
        games.append(
            {**row, "ranks": ranks(event), "event_id": str(event.get("id")), "state": _state(event)}
        )
    week = week_number(payload)
    return {
        "week": week,
        "week_label": f"Week {week}" if week else "",
        "fetched_at": (now or datetime.now(UTC)).isoformat(),
        "games": games,
    }


def needs_next_week(payload: dict) -> bool:
    """True once every top-25 game on this scoreboard has started: the
    reader is then looking ahead to next week's slate."""
    events = top25(payload)
    return bool(events) and all(_state(e) in ("in", "post") for e in events)


def slate_teams(slate_state: dict) -> set[str]:
    teams = set()
    for g in slate_state.get("games") or []:
        codes = vegas.matchup_teams(g.get("game"))
        if codes:
            teams.update(codes)
    return teams


def finals(payload: dict, teams: set[str]) -> list[str]:
    """Event ids of finished games involving any of these teams."""
    out = []
    for event in payload.get("events") or []:
        if _state(event) != "post":
            continue
        abbrs = {
            (c.get("team") or {}).get("abbreviation")
            for c in _competition(event).get("competitors") or []
        }
        if abbrs & teams:
            out.append(str(event.get("id")))
    return out


# --- a box score, reduced -----------------------------------------------------


def _num(text: str) -> float:
    try:
        return float(str(text).replace(",", ""))
    except ValueError:
        return 0.0


def reduce_box(summary: dict, event_id: str) -> dict | None:
    """{"id", "date", "teams": {abbr: opponent}, "players": {athlete id:
    {"name", "team", "opp", stat: value}}} -- the three categories the
    markets read, nothing else. None when the summary carries no box."""
    header = summary.get("header") or {}
    date = ""
    for comp in header.get("competitions") or []:
        date = comp.get("date") or date
    sides = (summary.get("boxscore") or {}).get("players") or []
    abbrs = [((s.get("team") or {}).get("abbreviation") or "") for s in sides]
    if len(sides) != 2 or not all(abbrs):
        return None
    teams = {abbrs[0]: abbrs[1], abbrs[1]: abbrs[0]}
    players: dict[str, dict] = {}
    for side, abbr in zip(sides, abbrs, strict=True):
        for cat in side.get("statistics") or []:
            name = cat.get("name")
            if name not in _CATEGORIES:
                continue
            keys = cat.get("keys") or []
            labels = cat.get("labels") or []
            columns = []
            for i in range(max(len(keys), len(labels))):
                key = keys[i] if i < len(keys) else ""
                label = labels[i] if i < len(labels) else ""
                field = (
                    _CATEGORIES[name].get(key)
                    or _CATEGORIES[name].get(label)
                    or _SHARED_LABELS[name].get(label)
                )
                columns.append(field)
            for entry in cat.get("athletes") or []:
                athlete = entry.get("athlete") or {}
                aid = str(athlete.get("id") or "")
                if not aid:
                    continue
                row = players.setdefault(
                    aid,
                    {"name": athlete.get("displayName") or "", "team": abbr, "opp": teams[abbr]},
                )
                for field, value in zip(columns, entry.get("stats") or [], strict=False):
                    if field == "cmp_att":
                        cmp_, _, att = str(value).partition("/")
                        row["pass_cmp"], row["pass_att"] = _num(cmp_), _num(att)
                    elif field:
                        row[field] = _num(value)
    return {"id": str(event_id), "date": date, "teams": teams, "players": players}


# --- the stored season --------------------------------------------------------


def blank() -> dict:
    return {"v": VERSION, "slate": {}, "boxes": {}}


def current(state: dict | None) -> dict:
    if not state or state.get("v") != VERSION:
        return blank()
    return state


def known_events(state: dict | None) -> list[str]:
    return sorted((current(state).get("boxes") or {}).keys())


_SLATE_FIELDS = (
    "game",
    "fav",
    "total",
    "imp",
    "read",
    "kickoff",
    "away_name",
    "home_name",
    "tv",
    "weather",
    "weather_id",
    "event_id",
    "state",
)


def clean_slate(raw: dict | None) -> dict:
    """Rebuilt field by field: this renders into the page."""
    games = []
    for row in ((raw or {}).get("games") or [])[:40]:
        if not isinstance(row, dict) or not row.get("game"):
            continue
        g = {f: str(row.get(f) or "") for f in _SLATE_FIELDS}
        g["ranks"] = {
            str(k)[:8]: int(v)
            for k, v in (row.get("ranks") or {}).items()
            if isinstance(v, int) and 1 <= v <= TOP
        }
        games.append(g)
    week = (raw or {}).get("week")
    return {
        "week": week if isinstance(week, int) else None,
        "week_label": str((raw or {}).get("week_label") or "")[:20],
        "fetched_at": str((raw or {}).get("fetched_at") or ""),
        "games": games,
    }


def clean_box(raw: dict | None) -> dict | None:
    if not isinstance(raw, dict) or not raw.get("id"):
        return None
    teams = {str(k)[:8]: str(v)[:8] for k, v in (raw.get("teams") or {}).items()}
    if len(teams) != 2:
        return None
    players = {}
    for aid, p in (raw.get("players") or {}).items():
        if not isinstance(p, dict) or p.get("team") not in teams:
            continue
        row = {"name": str(p.get("name") or "")[:60], "team": p["team"], "opp": teams[p["team"]]}
        for stat in STATS:
            v = p.get(stat)
            if isinstance(v, int | float):
                row[stat] = float(v)
        players[str(aid)[:20]] = row
    return {
        "id": str(raw["id"])[:20],
        "date": str(raw.get("date") or "")[:25],
        "teams": teams,
        "players": players,
    }


def merge(state: dict | None, slate_raw: dict | None, boxes: list | None) -> dict:
    """The new slate replaces the old; boxes add by event id, so a
    re-pushed game replaces itself rather than counting twice."""
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
    return state


# --- the season as game logs --------------------------------------------------
#
# Shaped like app/feeds/gamelogs.py's state -- {pid: {"pos", "games":
# {"2026-<yyyymmdd>": {...}}}} -- so its per-player log and its "what a
# defense allowed" table read college games with no second copy of either.
# A team plays at most once a day, so the date is a unique, ordered key.

# A role, read from volume: a passer throws 10+ a game; everyone else is a
# rusher or a receiver by which he does more of. Named QB/RB/WR only as
# the internal keys the shared code reads; the page labels them Passer,
# Rusher, Receiver, because the box score publishes no position.
PASSER_ATTEMPTS = 10.0


def to_logs(state: dict | None) -> dict:
    per_player: dict[str, dict] = {}
    for box in (current(state).get("boxes") or {}).values():
        day = "".join(ch for ch in str(box.get("date") or "")[:10] if ch.isdigit())
        if len(day) != 8:
            continue
        for aid, p in (box.get("players") or {}).items():
            game = {"t": p["team"], "o": p["opp"]}
            for stat in STATS:
                if p.get(stat):
                    game[stat] = p[stat]
            entry = per_player.setdefault(aid, {"name": p["name"], "team": p["team"], "games": {}})
            entry["games"][f"{SEASON}-{day}"] = game
            entry["team"] = p["team"]  # the most recent box read wins below
    players = {}
    for aid, entry in per_player.items():
        games = entry["games"]
        n = len(games)
        pass_att = sum(g.get("pass_att", 0) for g in games.values()) / n
        rush_att = sum(g.get("rush_att", 0) for g in games.values()) / n
        rec = sum(g.get("rec", 0) for g in games.values()) / n
        role = "QB" if pass_att >= PASSER_ATTEMPTS else ("RB" if rush_att >= rec else "WR")
        latest = max(games)
        players[aid] = {
            "pos": role,
            "name": entry["name"],
            "team": games[latest]["t"],
            "games": games,
        }
    # No "v": the composer stamps the game-log version it reads with.
    return {"weeks": {}, "players": players}
