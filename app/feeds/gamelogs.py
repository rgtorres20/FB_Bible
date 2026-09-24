"""Every skill player's game-by-game box scores, this season and last.

Owner, Sep 24: "yes" to the stats behind each pick -- the game log, how
often a player went over the line typed in, and what this week's opponent
allows to his position. All three are counts of real games, so this unit
keeps the games themselves rather than any summary of them.

Source: Sleeper's per-week stats rows (probe runs 38-40, 2026-09-24). Every
row carries the player's `team` and `opponent` for that game, his position,
the game `date`, and a `stats` object in the scorer's own vocabulary, with
`gp` marking a game he actually played (425 of 708 rows in 2026 Week 2 --
the rest were active and did not play). The team is the one he played
for that week, so a traded player's games stay with the right defense.

Folded a few weeks per sync: one week for QB/RB/WR/TE is ~700KB, and the
whole of last season would not fit one serverless call. A week is only
marked final two days after its last game, because Sleeper applies stat
corrections after Monday night; until then it is re-fetched each sync.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import httpx

URL = (
    "https://api.sleeper.com/stats/nfl/{season}/{week}?season_type=regular"
    "&position[]=QB&position[]=RB&position[]=WR&position[]=TE"
)
POSITIONS = ("QB", "RB", "WR", "TE")
# The markets the FFBets tabs offer, plus what they are made of.
KEEP = (
    "pass_yd",
    "pass_td",
    "rush_att",
    "rush_yd",
    "rush_td",
    "rec_tgt",
    "rec",
    "rec_yd",
    "rec_td",
)
CURRENT = 2026
LAST = 2025
LAST_WEEKS = tuple(range(1, 19))
WEEKS_PER_SYNC = 3
FINAL_AFTER = timedelta(days=2)
VERSION = 1


def blank() -> dict:
    return {"v": VERSION, "weeks": {}, "players": {}}


def _current(state: dict | None) -> dict:
    if not state or state.get("v") != VERSION:
        return blank()
    return state


def _week_key(season: int, week: int) -> str:
    return f"{season}-{week}"


def pending(state: dict | None, slate_week: int | None, limit: int = WEEKS_PER_SYNC) -> list:
    """(season, week) pairs still to fetch, this season's played weeks first
    -- they are the ones a pick this week leans on -- then last season's."""
    weeks = _current(state).get("weeks") or {}
    todo = []
    for week in range(1, (slate_week or 1)):
        if weeks.get(_week_key(CURRENT, week)) != "final":
            todo.append((CURRENT, week))
    for week in LAST_WEEKS:
        if weeks.get(_week_key(LAST, week)) != "final":
            todo.append((LAST, week))
    return todo[:limit]


def season_complete(state: dict | None, season: int = LAST) -> bool:
    weeks = _current(state).get("weeks") or {}
    return all(weeks.get(_week_key(season, w)) == "final" for w in LAST_WEEKS)


async def fetch_week(season: int, week: int, client: httpx.AsyncClient | None = None) -> list:
    """One week's rows. Raises on a transport or HTTP failure, so the
    caller leaves the week unfetched and tries again next sync."""
    own = client is None
    client = client or httpx.AsyncClient(
        timeout=60.0, headers={"User-Agent": "FBBible/1.0 (personal fantasy tool, weekly)"}
    )
    try:
        response = await client.get(URL.format(season=season, week=week))
        response.raise_for_status()
        rows = response.json()
    finally:
        if own:
            await client.aclose()
    return rows if isinstance(rows, list) else []


def fold(state: dict | None, season: int, week: int, rows: list, now: datetime) -> dict:
    """Replace one week's games with these rows. Replacing, not adding, so a
    re-fetch after a stat correction cannot count a game twice."""
    state = dict(_current(state))
    key = _week_key(season, week)
    players = {pid: dict(p) for pid, p in (state.get("players") or {}).items()}
    for p in players.values():
        games = dict(p.get("games") or {})
        games.pop(key, None)
        p["games"] = games
    latest: date | None = None
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        stats = row.get("stats") or {}
        position = ((row.get("player") or {}).get("position") or "").upper()
        pid = str(row.get("player_id") or "")
        try:
            played_on = date.fromisoformat(str(row.get("date") or ""))
            latest = played_on if latest is None or played_on > latest else latest
        except ValueError:
            pass
        if not pid or position not in POSITIONS or not stats.get("gp"):
            continue
        game = {"t": row.get("team") or "", "o": row.get("opponent") or ""}
        for field in KEEP:
            value = stats.get(field)
            if isinstance(value, int | float) and value:
                game[field] = value
        player = players.setdefault(pid, {"pos": position, "games": {}})
        player["pos"] = position
        player["games"][key] = game
    final = latest is not None and now.date() - latest >= FINAL_AFTER
    weeks = dict(state.get("weeks") or {})
    # An empty answer is an unplayed week, not a final one: fetch it again.
    weeks[key] = "final" if final else "partial"
    state["weeks"] = weeks
    state["players"] = {pid: p for pid, p in players.items() if p["games"]}
    return state


def season_games(state: dict | None, pid: str, season: int) -> list[dict]:
    """His games in one season, in week order, each with its week."""
    games = ((_current(state).get("players") or {}).get(str(pid)) or {}).get("games") or {}
    out = []
    for key, game in games.items():
        s, w = key.split("-")
        if int(s) == season:
            out.append({"w": int(w), **game})
    return sorted(out, key=lambda g: g["w"])


def player_log(state: dict | None, pid: str) -> dict:
    """What the panel needs for one player: both seasons' games, the
    market stats only, with a rush + rec TD total per game."""
    out = {}
    for season in (CURRENT, LAST):
        games = []
        for g in season_games(state, pid, season):
            row = {"w": g["w"], "o": g.get("o", "")}
            for field in ("pass_yd", "rush_yd", "rec", "rec_yd"):
                if g.get(field):
                    row[field] = g[field]
            td = (g.get("rush_td") or 0) + (g.get("rec_td") or 0)
            if td:
                row["td"] = td
            games.append(row)
        if games:
            out[str(season)[2:]] = games
    return out


# What a defense allowed, by the position of the man it allowed it to.
ALLOWED = ("pass_yd", "rush_yd", "rec", "rec_yd", "td")


def allowed(state: dict | None, season: int = CURRENT) -> dict:
    """{defense team: {"games": n, position: {stat: [per game, rank from
    the most, rank from the fewest, how many share it, how many defenses
    faced the position]}}}. Built from every played
    game's box score against that defense."""
    totals: dict[str, dict[str, dict[str, float]]] = {}
    games: dict[str, set[int]] = {}
    for player in (_current(state).get("players") or {}).values():
        pos = player.get("pos")
        for key, g in (player.get("games") or {}).items():
            s, w = key.split("-")
            if int(s) != season or not g.get("o"):
                continue
            defense = g["o"]
            games.setdefault(defense, set()).add(int(w))
            bucket = totals.setdefault(defense, {}).setdefault(pos, {})
            for stat in ALLOWED:
                value = (
                    (g.get("rush_td") or 0) + (g.get("rec_td") or 0)
                    if stat == "td"
                    else g.get(stat) or 0
                )
                bucket[stat] = bucket.get(stat, 0.0) + value
    per_game: dict[str, dict[str, dict[str, float]]] = {
        d: {
            pos: {stat: v / len(games[d]) for stat, v in stats.items()}
            for pos, stats in by_pos.items()
        }
        for d, by_pos in totals.items()
    }
    out: dict[str, dict] = {d: {"games": len(games[d])} for d in per_game}
    for pos in POSITIONS:
        for stat in ALLOWED:
            faced = [d for d in per_game if pos in per_game[d]]
            values = {d: round(per_game[d][pos].get(stat, 0.0), 1) for d in faced}
            for d in faced:
                v = values[d]
                # Competition ranking from both ends, so a tie is never
                # dressed up as an order, among the defenses that faced
                # this position.
                out[d].setdefault(pos, {})[stat] = [
                    v,
                    1 + sum(1 for x in values.values() if x > v),
                    1 + sum(1 for x in values.values() if x < v),
                    sum(1 for x in values.values() if x == v),
                    len(faced),
                ]
    return out
