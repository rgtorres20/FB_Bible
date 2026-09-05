"""The game stack: this week's slate, ranked by projected fantasy points.

Owner ask, Sep 3: "show who would be the potential best games for
fantasy points and list them from highest to lowest and show me the
expected projection for highest scores" -- and, for the Predictions tab,
"compare Vegas lines to assist in totals" and "people being out impacts
other player ceiling for points".

All of it is arithmetic over feeds the app already stores, joined by
Sleeper's player id -- nothing here is a model's opinion:

- **the projection** is Rotowire's weekly line (via Sleeper,
  `projections.reduce_week`), run through each league's own scoring
  (`League.score_offense`), so a quarterback's number differs between
  NDDPL and RED_EYE the way it does on every other board;
- **the game total** is the sum of both sides' projected skill players
  (QB/RB/WR/TE -- kickers and team defenses have no weekly line in the
  store, and are not what "best game for fantasy points" means);
- **the line** is the slate's own favorite and total, with each side's
  implied points recomputed by the odds unit;
- **the alerts** are Sleeper's current injury flag per player and the
  newest polled wire item that tags him (a join, not a search);
- **the vacancies** are `depth.next_man_up`: a starter flagged out, how
  much of his team's '25 work comes loose, and the next man measured
  behind him with *his* projected line -- what "somebody being out
  changes a teammate's ceiling" is, without a made-up multiplier.

Honesty rules that bind this module: a game with no projected player on
either side is reported as uncovered, never as a zero-point game; a
player the forecast does not cover has no number; the ranking league is
the visitor's first league and every league's figure is carried so the
panel can re-sort without a round trip. The chosen constants are in
docs/ASSUMPTIONS.md.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .. import leagues as leagues_mod
from . import depth, projections, vegas
from .clock import format_time

# ESPN's slate names Washington WSH; Sleeper's index -- and every projection
# row, which joins by Sleeper id -- says WAS. The one divergence between the
# two vocabularies. `vegas.implied_by_team` already refuses to guess across
# it; this map is how the Commanders' players stop being a game with nobody
# in it (docs/ASSUMPTIONS.md).
SLATE_TO_INDEX = {"WSH": "WAS"}

SKILL_POSITIONS = ("QB", "RB", "WR", "TE")

# How many projected scorers a game row names. Six is two full skill
# lineups' worth of headline players -- enough to see who carries the
# total, few enough to read on a phone (docs/ASSUMPTIONS.md).
TOP_N = 6

# A wire item older than this is not an alert, it is history.
WIRE_WINDOW = timedelta(days=7)


def _index_code(code: str) -> str:
    return SLATE_TO_INDEX.get(code, code)


def _points(line: dict, leagues: list[leagues_mod.League]) -> dict[str, float]:
    return {lg.key: lg.score_offense(line) for lg in leagues}


def team_lines(week_proj_state: dict | None, index: dict | None) -> dict[str, list[dict]]:
    """{index team code: projected skill players on it}, each carrying the
    stat line the scorer reads and Sleeper's current injury flag."""
    players = (index or {}).get("players") or {}
    lines = (week_proj_state or {}).get("players") or {}
    out: dict[str, list[dict]] = {}
    for pid, line in lines.items():
        player = players.get(pid)
        if not player or player.get("dst") or not line:
            continue
        position = (player.get("position") or "").upper()
        team = player.get("team") or ""
        if position not in SKILL_POSITIONS or not team:
            continue
        out.setdefault(team, []).append(
            {
                "id": pid,
                "name": player.get("name") or "",
                "position": position,
                "team": team,
                "injury": (player.get("injury_status") or "").strip(),
                "line": line,
            }
        )
    return out


def team_tds(rows: list[dict]) -> dict[str, float]:
    """A side's projected offensive touchdowns. Rushing plus receiving:
    a passing TD and the receiving TD it throws are the same score, so
    adding pass_td would count every one of them twice."""
    rush = sum(r["line"].get("rush_td", 0) for r in rows)
    rec = sum(r["line"].get("rec_td", 0) for r in rows)
    return {"rush_td": round(rush, 1), "rec_td": round(rec, 1), "total": round(rush + rec, 1)}


def movement(vegas_state: dict | None, game: str) -> str:
    """'O/U 47.5 → 48.5 since Tue Sep 8 · 9:15 AM' from the push history, or ''.

    The oldest snapshot the store still holds is "open" here -- about a
    day back, not the book's true opener (docs/ASSUMPTIONS.md). No history,
    no movement, no clause: a single snapshot is not a move.
    """
    history = [h for h in ((vegas_state or {}).get("history") or []) if isinstance(h, dict)]
    points = [(h.get("at") or "", (h.get("lines") or {}).get(game)) for h in history]
    points = [(at, line) for at, line in points if line and line.get("total")]
    if len(points) < 2:
        return ""
    first_at, first = points[0]
    _, last = points[-1]
    try:
        was, now_total = float(first["total"]), float(last["total"])
    except ValueError:
        return ""
    if was == now_total:
        return f"O/U unchanged since {format_time(first_at)}"
    return f"O/U {was:g} → {now_total:g} since {format_time(first_at)}"


# The weather read is a rule, not a model (docs/ASSUMPTIONS.md) -- the
# owner's own words: "a wet game may cause less points just like a snow
# game, but a fair weather day means easier to control outcomes". Keyed on
# ESPN's forecast text, labelled "(rule)" wherever it renders, and absent
# when there is no forecast (a dome, or a slate too far out).
_WEATHER_RULES = (
    (
        ("snow", "sleet", "blizzard", "wintry"),
        "snow: expect fewer points and a run-leaning script",
    ),
    (
        ("thunder", "storm", "rain", "shower", "drizzle", "wet"),
        "wet: passing volume tends to fall; lean run and the short game",
    ),
    (
        ("wind", "gust", "breez"),
        "wind: deep passing and kicking get harder; the run game holds",
    ),
)


def weather_read(text: str) -> str:
    low = (text or "").lower()
    for needles, verdict in _WEATHER_RULES:
        if any(n in low for n in needles):
            return verdict
    return "fair: no weather penalty on the forecast" if low else ""


def _weather(game: dict) -> dict | None:
    text = (game.get("weather") or "").strip()
    if not text:
        return None
    return {"summary": text, "read": weather_read(text)}


def _wire(item: dict | None, now: datetime) -> dict | None:
    if not item:
        return None
    published = item.get("published") or ""
    try:
        when = datetime.fromisoformat(published.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    if now - when > WIRE_WINDOW:
        return None
    return {
        "head": (item.get("title") or "").strip(),
        "link": item.get("link", ""),
        "source": item.get("source_name", ""),
        "time": format_time(published),
    }


def vacancies(
    index: dict | None,
    stats_state: dict | None,
    week_proj_state: dict | None,
    leagues: list[leagues_mod.League],
) -> dict[str, list[dict]]:
    """{index team code: [starter out -> next man, with his projection]}.

    The vacancy is measured ('25 opportunity, `depth.next_man_up`); the
    next man's number is Rotowire's own line for him this week, or absent
    when the forecast does not cover him. Nothing is redistributed by
    hand -- a multiplier would be this app's invention wearing the
    forecaster's name.
    """
    lines = (week_proj_state or {}).get("players") or {}
    out: dict[str, list[dict]] = {}
    for row in depth.next_man_up(index, stats_state):
        if row["position"] not in SKILL_POSITIONS:
            continue
        starter, nxt = row["starter"], row["replacement"]
        line = lines.get(nxt["id"])
        out.setdefault(row["team"], []).append(
            {
                "position": row["position"],
                "starter": starter["name"],
                "injury": starter["injury"],
                "vacated": round(starter["opportunity"]),
                "next": nxt["name"],
                "next_injury": nxt["injury"],
                "next_points": _points(line, leagues) if line else None,
                "room_all_out": row["room_all_out"],
            }
        )
    return out


def build(
    vegas_state: dict | None,
    week_proj_state: dict | None,
    index: dict | None,
    stats_state: dict | None,
    items: list[dict] | None,
    leagues: list[leagues_mod.League],
    now: datetime | None = None,
    previews: dict[str, str] | None = None,
) -> dict | None:
    """The ranked slate, or None when there is nothing honest to rank:
    no slate, no league, or no weekly forecast in the store."""
    games = (vegas_state or {}).get("games") or []
    if not games or not leagues:
        return None
    by_team = team_lines(week_proj_state, index)
    if not by_team:
        return None
    now = now or datetime.now(UTC)
    implied = vegas.implied_by_team(games)
    outs = vacancies(index, stats_state, week_proj_state, leagues)
    ids = {r["id"] for rows in by_team.values() for r in rows}
    mentions = depth.latest_mentions(items, ids)
    default = leagues[0].key
    previews = previews or {}

    ranked: list[dict] = []
    uncovered: list[str] = []
    for game in games:
        codes = vegas.matchup_teams(game.get("game"))
        if not codes:
            continue
        away, home = codes
        players: list[dict] = []
        sides: dict[str, dict] = {}
        for code in codes:
            rows = by_team.get(_index_code(code), [])
            scored = [{**r, "points": _points(r["line"], leagues)} for r in rows]
            sides[code] = {
                "points": {
                    lg.key: round(sum(p["points"][lg.key] for p in scored), 1) for lg in leagues
                },
                "tds": team_tds(rows),
                "covered": len(scored),
            }
            players.extend(scored)
        if not players:
            uncovered.append(game.get("game") or "")
            continue
        top = sorted(players, key=lambda p: -p["points"][default])[:TOP_N]
        game_out = []
        for code in codes:
            for v in outs.get(_index_code(code), []):
                game_out.append({**v, "team": code})
        away_name, home_name = game.get("away_name") or away, game.get("home_name") or home
        ranked.append(
            {
                "game": game.get("game"),
                "away": away,
                "home": home,
                "away_name": away_name,
                "home_name": home_name,
                "kickoff": format_time(game.get("kickoff")),
                "tv": game.get("tv") or "",
                "fav": game.get("fav") or "",
                "total": game.get("total") or "",
                "implied": {c: implied[c] for c in codes if c in implied},
                "movement": movement(vegas_state, game.get("game") or ""),
                "weather": _weather(game),
                "points": {
                    lg.key: {
                        "total": round(sum(s["points"][lg.key] for s in sides.values()), 1),
                        away: sides[away]["points"][lg.key],
                        home: sides[home]["points"][lg.key],
                    }
                    for lg in leagues
                },
                "tds": {c: sides[c]["tds"] for c in codes},
                "covered": {c: sides[c]["covered"] for c in codes},
                "top": [
                    {
                        "id": p["id"],
                        "name": p["name"],
                        "position": p["position"],
                        "team": next((c for c in codes if _index_code(c) == p["team"]), p["team"]),
                        "points": p["points"],
                        "injury": p["injury"],
                        "wire": _wire(mentions.get(p["id"]), now),
                    }
                    for p in top
                ],
                "out": game_out,
                "preview": previews.get(f"{away_name} @ {home_name}", ""),
            }
        )
    ranked.sort(key=lambda g: -g["points"][default]["total"])
    for n, game in enumerate(ranked, 1):
        game["rank"] = n
    return {
        "week": (week_proj_state or {}).get("week"),
        "source": projections.source_label(week_proj_state),
        "as_of": projections.as_of(week_proj_state),
        "leagues": [{"key": lg.key, "name": lg.name} for lg in leagues],
        "default_league": default,
        "games": ranked,
        "uncovered": uncovered,
        "note": (
            "Projected fantasy points are each side's projected QB/RB/WR/TE lines under "
            "the league's own scoring, summed; kickers, team defenses and return yards are "
            "not in the forecast. The Vegas line is context, not an input to the ranking."
        ),
    }


def projected_top_by_team(
    vegas_state: dict | None,
    week_proj_state: dict | None,
    index: dict | None,
    leagues: list[leagues_mod.League],
    limit: int = 3,
) -> dict[str, list[dict]]:
    """{slate team code: top projected scorers} for the AI preview work
    list -- names, positions, the first league's projected points, and
    the flag or practice status Sleeper carries. Only teams on the slate,
    only players with a line: the model gets numbers we fetched."""
    if not leagues:
        return {}
    by_team = team_lines(week_proj_state, index)
    players = (index or {}).get("players") or {}
    key = leagues[0].key
    out: dict[str, list[dict]] = {}
    for game in (vegas_state or {}).get("games") or []:
        codes = vegas.matchup_teams(game.get("game"))
        if not codes:
            continue
        for code in codes:
            rows = by_team.get(_index_code(code), [])
            scored = sorted(
                ({**r, "pts": _points(r["line"], leagues)[key]} for r in rows),
                key=lambda r: -r["pts"],
            )[:limit]
            if not scored:
                continue
            out[code] = [
                {
                    "name": r["name"],
                    "position": r["position"],
                    "projected_points": r["pts"],
                    "league": leagues[0].name,
                    **({"injury": r["injury"]} if r["injury"] else {}),
                    **(
                        {"practice": players.get(r["id"], {}).get("practice")}
                        if players.get(r["id"], {}).get("practice")
                        else {}
                    ),
                }
                for r in scored
            ]
    return out


# --- weekly stars: the week's best projected players, by position ----------

IDP_GROUPS = ("DB", "LB", "DL")


def weekly_stars(
    week_proj_state: dict | None,
    index: dict | None,
    items: list[dict] | None,
    leagues: list[leagues_mod.League],
    now: datetime | None = None,
    per_position: int = 12,
) -> dict | None:
    """This week's projected leaders, per position, under each league's
    scoring -- the start/sit list (owner, Sep 3: "players with best value
    for the week, this helps drive who I play").

    Offense is scored by `score_offense`; defenders by `score_idp` under
    the groups a league starts, with projected tackles carried beside the
    points because that is the volume that decides IDP weeks ("usually I
    just want to know tackles"). A league that cannot start a group has
    no number for it -- a dash, never a zero. Every row carries Sleeper's
    flag and practice status and the newest wire item that tags him.
    """
    lines = (week_proj_state or {}).get("players") or {}
    players = (index or {}).get("players") or {}
    if not lines or not players or not leagues:
        return None
    now = now or datetime.now(UTC)
    mentions = depth.latest_mentions(items, set(lines))
    groups: dict[str, list[dict]] = {}
    for pid, line in lines.items():
        p = players.get(pid)
        if not p or p.get("dst") or not line:
            continue
        idp = p.get("idp")
        position = idp or (p.get("position") or "").upper()
        if position not in (*SKILL_POSITIONS, *IDP_GROUPS):
            continue
        if idp:
            points = {lg.key: lg.score_player(line, idp_group=idp) for lg in leagues}
        else:
            points = _points(line, leagues)
        if all(v is None for v in points.values()):
            continue
        solo = line.get("idp_tkl_solo", 0) or 0
        ast = line.get("idp_tkl_ast", 0) or 0
        groups.setdefault(position, []).append(
            {
                "id": pid,
                "name": p.get("name") or "",
                "position": position,
                "slot": p.get("position") or position,
                "team": p.get("team") or "",
                "points": points,
                "tackles": round(solo + ast, 1) if idp else None,
                "solo": round(solo, 1) if idp else None,
                "injury": (p.get("injury_status") or "").strip(),
                "practice": p.get("practice") or "",
                "depth": p.get("depth_order"),
                "wire": _wire(mentions.get(pid), now),
            }
        )
    default = leagues[0].key

    def lead(row: dict) -> float:
        v = row["points"].get(default)
        return v if v is not None else -1.0

    for rows in groups.values():
        rows.sort(key=lambda r: -lead(r))
        del rows[per_position:]
    return {
        "week": (week_proj_state or {}).get("week"),
        "source": projections.source_label(week_proj_state),
        "as_of": projections.as_of(week_proj_state),
        "leagues": [{"key": lg.key, "name": lg.name} for lg in leagues],
        "default_league": default,
        "positions": [pos for pos in (*SKILL_POSITIONS, *IDP_GROUPS) if pos in groups],
        "groups": groups,
        "note": (
            "Projected points under each league's own scoring; defenders under the IDP "
            "values of the groups that league starts, with projected tackles (solo + "
            "assisted) beside them. A dash means that league cannot start him."
        ),
    }


# --- clauses for the Predictions (FFBets) rows -------------------------------


def _team_of(pred: dict) -> str:
    return (pred.get("meta") or "").split("·")[-1].strip()


def lean_clauses(
    stack: dict | None,
    preds: list[dict],
    outs: dict[str, list[dict]] | None = None,
) -> dict[str, str]:
    """{prediction row name: labelled clause} comparing the line to the
    forecast for that row's team, plus any starter out on it.

    "Vegas implies BUF 27.5 · Rotowire (via Sleeper) projects BUF skill
    players for 3.4 TDs this week (2.1 rec + 1.3 rush)." Two measured
    numbers side by side; the reader does the comparing. The lean and
    the confidence are never touched -- same contract as every other
    clause on that tab.
    """
    if not stack:
        return {}
    by_team: dict[str, dict] = {}
    for game in stack.get("games") or []:
        for code in (game["away"], game["home"]):
            by_team[code] = {
                "implied": game["implied"].get(code),
                "tds": game["tds"][code],
                "covered": game["covered"][code],
                "movement": game.get("movement") or "",
                "weather": game.get("weather"),
            }
    label = stack.get("source") or projections.ATTRIBUTION
    week = stack.get("week")
    out: dict[str, str] = {}
    for pred in preds:
        team = _team_of(pred)
        side = by_team.get(team)
        bits: list[str] = []
        if side and side["covered"]:
            implied = side["implied"]
            tds = side["tds"]
            lead = (
                f"Vegas implies {team} {implied:g}"
                if implied is not None
                else f"{team}: no line posted"
            )
            move = side.get("movement") or ""
            bits.append(
                f"{lead}{' (' + move + ')' if move else ''} · {label} projects {team} skill "
                f"players for {tds['total']:g} TDs in Wk {week} "
                f"({tds['rec_td']:g} rec + {tds['rush_td']:g} rush)."
            )
            if side.get("weather"):
                bits.append(
                    f"Weather: {side['weather']['summary']} — {side['weather']['read']} (rule)."
                )
        for v in (outs or {}).get(_index_code(team), []):
            nxt = v["next"]
            pts = v["next_points"]
            first = next(iter(pts.values())) if pts else None
            proj = f", projected {first:g} pts" if first is not None else ", no weekly line"
            bits.append(
                f"Out on {team}: {v['starter']} ({v['position']}, {v['injury']}), "
                f"{v['vacated']} '25 touches/targets come loose → {nxt}{proj}."
            )
        if bits:
            out[pred["name"]] = " ".join(bits)
    return out
