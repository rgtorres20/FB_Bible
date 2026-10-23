"""NBA research (owner, Oct 23: "what is out there to measure ... matchups,
strong players vs weak ... minutes will matter, more minutes more points").

Runs on the Actions runner (ESPN 403s the sandbox). Two parts:

  sources -- what free data exists beyond the box scores the panel reads:
             projections, prop lines, team stats, pace. Status + shape only.
  study   -- 2025-26 regular season, every rotation player's ESPN game log,
             backtested chronologically (each game predicted only from the
             games before it). Measures what moves points, rebounds and
             assists: minutes, the opponent, rest, home/away, teammates out.

Research only -- nothing here is imported by the app.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics as st
import sys
from collections import defaultdict
from datetime import date

import httpx

UA = {"User-Agent": "FBBible/1.0 (personal fantasy tool, research)"}
SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
GAMELOG = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{}/gamelog"


def shape(obj, depth=0, limit=2):
    pad = "  " * depth
    if isinstance(obj, dict):
        keys = list(obj)
        print(f"{pad}dict({len(keys)}): {keys[:25]}")
        if depth < limit:
            for k in keys[:6]:
                if isinstance(obj[k], dict | list):
                    print(f"{pad} .{k}:")
                    shape(obj[k], depth + 1, limit)
    elif isinstance(obj, list):
        print(f"{pad}list({len(obj)})")
        if obj and depth < limit:
            shape(obj[0], depth + 1, limit)
    else:
        print(f"{pad}{str(obj)[:120]!r}")


async def try_get(http, label, url, headers=None, show=True, limit=2):
    try:
        r = await http.get(url, headers={**UA, **(headers or {})}, timeout=20)
    except Exception as exc:  # noqa: BLE001
        print(f"\n### {label}: {type(exc).__name__} {exc}"[:300])
        return None
    print(f"\n### {label}: HTTP {r.status_code} · {len(r.content):,} bytes")
    if r.status_code != 200:
        print("  " + r.text[:200].replace("\n", " "))
        return None
    try:
        data = r.json()
    except ValueError:
        print("  (not JSON) " + r.text[:200].replace("\n", " "))
        return None
    if show:
        shape(data, limit=limit)
    return data


async def sources():
    async with httpx.AsyncClient(follow_redirects=True) as http:
        board = await try_get(http, "ESPN scoreboard today", f"{SITE}/scoreboard", show=False)
        eid = str(((board or {}).get("events") or [{}])[0].get("id") or "")
        print(f"  first event: {eid}")
        summ = await try_get(http, "ESPN summary (keys)", f"{SITE}/summary?event={eid}", limit=0)
        if summ:
            for key in ("pickcenter", "predictor", "againstTheSpread", "injuries", "leaders"):
                if key in summ:
                    print(f"  summary.{key}:")
                    shape(summ[key], 2, 3)
        core = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba"
        odds = await try_get(
            http, "ESPN core odds", f"{core}/events/{eid}/competitions/{eid}/odds", limit=1
        )
        for item in ((odds or {}).get("items") or [])[:3]:
            ref = (item.get("$ref") or "").split("?")[0]
            if ref:
                o = await try_get(http, f"  odds item {ref[-40:]}", ref, limit=1)
                pid = ((o or {}).get("provider") or {}).get("id")
                if pid:
                    await try_get(
                        http,
                        f"  propBets provider {pid}",
                        f"{core}/events/{eid}/competitions/{eid}/odds/{pid}/propBets?limit=5",
                        limit=3,
                    )
        await try_get(http, "ESPN team statistics (ATL)", f"{SITE}/teams/1/statistics", limit=3)
        await try_get(
            http,
            "ESPN core team stats 2027",
            f"{core}/seasons/2027/types/2/teams/1/statistics",
            limit=2,
        )
        flt = json.dumps({"players": {"limit": 3, "sortPercOwned": {"sortAsc": False, "sortPriority": 1}}})
        fan = await try_get(
            http,
            "ESPN fantasy (fba) players + projections",
            "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/2027/segments/0/"
            "leaguedefaults/1?view=kona_player_info",
            headers={"X-Fantasy-Filter": flt},
            show=False,
        )
        for p in ((fan or {}).get("players") or [])[:1]:
            player = p.get("player") or {}
            print(f"  {player.get('fullName')}: {len(player.get('stats') or [])} stat blocks")
            for s in player.get("stats") or []:
                keys = list((s.get("stats") or {}))[:8]
                print(
                    f"   source {s.get('statSourceId')} split {s.get('statSplitTypeId')} "
                    f"period {s.get('scoringPeriodId')} id {s.get('id')} keys {keys}"
                )
        for url in (
            "https://api.sleeper.com/projections/nba/2027?season_type=regular",
            "https://api.sleeper.app/projections/nba/regular/2027/1",
            "https://api.sleeper.app/v1/state/nba",
        ):
            await try_get(http, f"Sleeper {url[24:]}", url, limit=1)
        await try_get(
            http,
            "stats.nba.com league team stats",
            "https://stats.nba.com/stats/leaguedashteamstats?Season=2025-26&SeasonType=Regular%20Season"
            "&MeasureType=Advanced&PerMode=PerGame&LeagueID=00&LastNGames=0&Month=0&OpponentTeamID=0"
            "&PaceAdjust=N&Period=0&PlusMinus=N&Rank=N&TeamID=0&DateFrom=&DateTo=&GameScope=&GameSegment="
            "&Location=&Outcome=&PORound=0&PlayerExperience=&PlayerPosition=&SeasonSegment=&ShotClockRange="
            "&StarterBench=&TwoWay=0&VsConference=&VsDivision=&Conference=&Division=&ISTRound=",
            headers={"Referer": "https://www.nba.com/", "Origin": "https://www.nba.com",
                     "Accept": "application/json"},
            limit=1,
        )
        await try_get(http, "cdn.nba.com today's scoreboard",
                      "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json",
                      limit=2)
        await try_get(http, "PrizePicks projections (NBA)",
                      "https://api.prizepicks.com/projections?league_id=7&per_page=5", limit=1)
        await try_get(http, "Underdog over/under lines",
                      "https://api.underdogfantasy.com/beta/v5/over_under_lines", show=False)


# --- the study -------------------------------------------------------------


async def roster_ids(http):
    teams = (await http.get(f"{SITE}/teams", headers=UA)).json()
    ids = []
    for t in teams["sports"][0]["leagues"][0]["teams"]:
        tid = t["team"]["id"]
        r = (await http.get(f"{SITE}/teams/{tid}/roster", headers=UA)).json()
        ids += [str(a["id"]) for a in r.get("athletes") or []]
    return ids


def num(v):
    try:
        return float(str(v).split("-")[0])
    except ValueError:
        return None


async def gamelog(http, sem, aid):
    async with sem:
        try:
            r = await http.get(GAMELOG.format(aid), params={"season": "2026"}, headers=UA, timeout=30)
            return aid, r.json() if r.status_code == 200 else None
        except Exception:  # noqa: BLE001
            return aid, None


def rows_of(aid, payload, keys_seen):
    labels = payload.get("labels") or []
    idx = {lab: i for i, lab in enumerate(labels)}
    need = ("MIN", "PTS", "REB", "AST", "FG", "FT", "3PT", "TO")
    if not all(n in idx for n in need):
        return []
    meta = payload.get("events") or {}
    out = []
    for stype in payload.get("seasonTypes") or []:
        if "regular" not in str(stype.get("displayName") or "").lower():
            continue
        for cat in stype.get("categories") or []:
            for ev in cat.get("events") or []:
                s = ev.get("stats") or []
                m = meta.get(str(ev.get("eventId"))) or {}
                if not keys_seen:
                    keys_seen.update(m.keys())
                mins = num(s[idx["MIN"]])
                if not mins:
                    continue
                fga = str(s[idx["FG"]]).split("-")
                fta = str(s[idx["FT"]]).split("-")
                out.append(
                    {
                        "aid": aid,
                        "eid": str(ev.get("eventId")),
                        "day": str(m.get("gameDate") or "")[:10],
                        "opp": (m.get("opponent") or {}).get("abbreviation") or "",
                        "team": (m.get("team") or {}).get("abbreviation") or "",
                        "home": m.get("atVs") == "vs",
                        "result": m.get("gameResult") or "",
                        "score": m.get("score") or "",
                        "hs": m.get("homeTeamScore"),
                        "as": m.get("awayTeamScore"),
                        "min": mins,
                        "pts": num(s[idx["PTS"]]) or 0.0,
                        "reb": num(s[idx["REB"]]) or 0.0,
                        "ast": num(s[idx["AST"]]) or 0.0,
                        "fga": float(fga[1]) if len(fga) == 2 else 0.0,
                        "fta": float(fta[1]) if len(fta) == 2 else 0.0,
                        "to": num(s[idx["TO"]]) or 0.0,
                    }
                )
    out.sort(key=lambda g: g["day"])
    return out


def mae(pairs):
    return st.mean(abs(a - b) for a, b in pairs) if pairs else float("nan")


def pct(x):
    return f"{100 * x:.1f}%"


def study_on(games_by_player):
    stats = ("pts", "reb", "ast")
    # Opponent allowed, accumulated chronologically: per (opp, day) totals of
    # what our logged players scored against that opponent.
    by_day = sorted({g["day"] for gs in games_by_player.values() for g in gs})
    opp_game = defaultdict(lambda: defaultdict(float))  # (opp, day) -> stat totals
    for gs in games_by_player.values():
        for g in gs:
            for s in stats + ("min",):
                opp_game[(g["opp"], g["day"])][s] += g[s]

    def opp_factor(opp, day, stat):
        """Allowed per game by `opp` before `day`, over the league mean before
        `day`. None until both sides have 8+ games."""
        mine = [v[stat] for (o, d), v in opp_game.items() if o == opp and d < day]
        if len(mine) < 8:
            return None
        league = [v[stat] for (o, d), v in opp_game.items() if d < day]
        return st.mean(mine) / st.mean(league)

    # cache factors per (opp, week) to keep this fast
    cache = {}

    def factor(opp, day, stat):
        key = (opp, day[:8] + str(int(day[8:10]) // 7), stat)
        if key not in cache:
            cache[key] = opp_factor(opp, day, stat)
        return cache[key]

    results = defaultdict(list)
    for gs in games_by_player.values():
        prev_day = None
        for i, g in enumerate(gs):
            past = gs[:i]
            rest = (date.fromisoformat(g["day"]) - date.fromisoformat(prev_day)).days if prev_day else None
            prev_day = g["day"]
            if len(past) < 10:
                continue
            mpg = st.mean(p["min"] for p in past)
            if mpg < 15:
                continue
            last5_min = st.mean(p["min"] for p in past[-5:])
            for s in stats:
                avg = st.mean(p[s] for p in past)
                per_min = sum(p[s] for p in past) / sum(p["min"] for p in past)
                last10 = st.mean(p[s] for p in past[-10:])
                f = factor(g["opp"], g["day"], s)
                results[s].append(
                    {
                        "actual": g[s],
                        "avg": avg,
                        "last10": last10,
                        "min_trend": per_min * last5_min,
                        "oracle_min": per_min * g["min"],
                        "opp": avg * f if f else None,
                        "both": per_min * last5_min * f if f else None,
                        "f": f,
                        "mpg": mpg,
                        "min": g["min"],
                        "min5": last5_min,
                        "rest": rest,
                        "home": g["home"],
                    }
                )
    return results


def report(results):
    for s, rows in results.items():
        print(f"\n===== {s.upper()} · {len(rows):,} player-games (10+ prior games, 15+ mpg) =====")
        print("Prediction error (mean absolute, lower is better):")
        for key, label in (
            ("avg", "season average to date (what the panel shows)"),
            ("last10", "last-10 average"),
            ("min_trend", "per-minute rate x last-5 minutes"),
            ("opp", "season average x opponent factor"),
            ("both", "per-minute x last-5 minutes x opponent factor"),
            ("oracle_min", "CEILING: per-minute rate x his ACTUAL minutes"),
        ):
            pairs = [(r[key], r["actual"]) for r in rows if r.get(key) is not None]
            base = [(r["avg"], r["actual"]) for r in rows if r.get(key) is not None]
            print(f"  {mae(pairs):6.2f}  vs avg {mae(base):6.2f}  ({len(pairs):,})  {label}")

        # Minutes: how much of the game-to-game swing is minutes?
        dev_s = [r["actual"] - r["avg"] for r in rows]
        dev_m = [r["min"] - r["mpg"] for r in rows]
        corr = st.correlation(dev_m, dev_s)
        slope = st.linear_regression(dev_m, dev_s).slope
        print(f"Minutes: corr(minutes above his norm, {s} above his norm) = {corr:.2f}; "
              f"each extra minute = {slope:+.2f} {s}  (r^2 {corr * corr:.2f})")
        for lo, hi in ((-99, -6), (-6, -2), (-2, 2), (2, 6), (6, 99)):
            band = [r for r in rows if lo <= r["min"] - r["mpg"] < hi]
            if band:
                over = sum(1 for r in band if r["actual"] > r["avg"]) / len(band)
                print(f"  minutes {lo:+d}..{hi:+d} vs norm: {len(band):5d} games, beat his average {pct(over)}")
        # Opponent: over the player's own average, by opponent rank band
        withf = [r for r in rows if r["f"] is not None]
        if withf:
            fs = sorted(r["f"] for r in withf)
            q = [fs[int(len(fs) * k / 5)] for k in range(1, 5)]
            print("Opponent (factor = what they allowed to date vs league; >1 = soft):")
            for name, lo, hi in (
                ("toughest 20%", 0, q[0]), ("tough", q[0], q[1]), ("middle", q[1], q[2]),
                ("soft", q[2], q[3]), ("softest 20%", q[3], 9),
            ):
                band = [r for r in withf if lo <= r["f"] < hi]
                stars = [r for r in band if r["avg"] >= (20 if s == "pts" else 8 if s == "reb" else 6)]
                role = [r for r in band if r not in stars]

                def beat(b):
                    return pct(sum(1 for r in b if r["actual"] > r["avg"]) / len(b)) if b else "-"

                gain = st.mean(r["actual"] - r["avg"] for r in band)
                print(f"  {name:13s} f {lo:.2f}-{hi:.2f}: {len(band):5d} g, vs avg {gain:+.2f}, "
                      f"beat avg {beat(band)} · stars {beat(stars)} ({len(stars)}) · role {beat(role)}")
        # Rest and venue
        for name, pick in (
            ("back-to-back (0 days rest)", lambda r: r["rest"] == 1),
            ("1 day rest", lambda r: r["rest"] == 2),
            ("2+ days rest", lambda r: r["rest"] is not None and r["rest"] >= 3),
            ("home", lambda r: r["home"]),
            ("away", lambda r: not r["home"]),
        ):
            band = [r for r in rows if pick(r)]
            if band:
                print(f"  {name:28s} {len(band):5d} g · {s} vs avg {st.mean(r['actual'] - r['avg'] for r in band):+.2f}"
                      f" · minutes vs norm {st.mean(r['min'] - r['mpg'] for r in band):+.2f}")


def teammates_out(games_by_player):
    """When a 30+ mpg teammate misses a game his team plays, what happens to
    the others' minutes and points? Team per game from the log's own team."""
    by_team_day = defaultdict(dict)
    for aid, gs in games_by_player.items():
        for g in gs:
            if g["team"]:
                by_team_day[(g["team"], g["day"])][aid] = g
    if not by_team_day:
        print("\n(teammate study skipped: the log carries no team per game)")
        return
    mpg = {a: st.mean(g["min"] for g in gs) for a, gs in games_by_player.items() if len(gs) >= 20}
    team_of = {}
    for (team, _d), players in by_team_day.items():
        for a in players:
            team_of.setdefault(a, defaultdict(int))[team] += 1
    deltas = defaultdict(list)
    for (team, day), present in by_team_day.items():
        regulars = [a for a, t in team_of.items() if max(t, key=t.get) == team and mpg.get(a, 0) >= 30]
        missing = [a for a in regulars if a not in present]
        for a, g in present.items():
            if a in mpg and mpg[a] >= 15 and a not in regulars:
                key = "star out" if missing else "full strength"
                base = st.mean(x["pts"] for x in games_by_player[a])
                deltas[key].append((g["min"] - mpg[a], g["pts"] - base, g["fga"]))
    print("\nTeammates out (others with 15-30 mpg, when a 30+ mpg teammate is missing):")
    for k, v in deltas.items():
        print(f"  {k:14s} {len(v):6d} g · minutes vs norm {st.mean(x[0] for x in v):+.2f} · "
              f"pts vs avg {st.mean(x[1] for x in v):+.2f}")


async def study():
    async with httpx.AsyncClient(follow_redirects=True) as http:
        ids = await roster_ids(http)
        print(f"current rosters: {len(ids)} players")
        sem = asyncio.Semaphore(12)
        logs = await asyncio.gather(*(gamelog(http, sem, a) for a in ids))
    keys_seen: set = set()
    games = {}
    for aid, payload in logs:
        if payload:
            rows = rows_of(aid, payload, keys_seen)
            if len(rows) >= 20:
                games[aid] = rows
    print(f"event metadata keys: {sorted(keys_seen)}")
    n = sum(len(v) for v in games.values())
    print(f"players with 20+ games in 2025-26: {len(games)} · {n:,} player-games")
    report(study_on(games))
    teammates_out(games)


# --- round 2 ------------------------------------------------------------------


async def sources2():
    async with httpx.AsyncClient(follow_redirects=True) as http:
        rows = (await http.get("https://api.sleeper.com/projections/nba/2027?season_type=regular",
                               headers=UA, timeout=30)).json()
        print(f"Sleeper NBA projections: {len(rows)} rows")
        companies = defaultdict(int)
        games = defaultdict(int)
        for r in rows:
            companies[r.get("company")] += 1
            games[r.get("game_id")] += 1
        print(f"  companies {dict(companies)}")
        print(f"  distinct game_id {len(games)}; sample {list(games.items())[:5]}")
        top = sorted(rows, key=lambda r: -float((r.get("stats") or {}).get("pts") or 0))[:3]
        for r in top:
            pl = r.get("player") or {}
            print(f"  {pl.get('first_name')} {pl.get('last_name')} {r.get('team')} game {r.get('game_id')} "
                  f"date {r.get('date')} week {r.get('week')}")
            print(f"    stats {json.dumps(r.get('stats'))[:600]}")
            print(f"    keys {sorted(r.keys())} player keys {sorted(pl.keys())[:20]}")
        for url in (
            "https://api.sleeper.com/projections/nba/2027?season_type=regular&week=1",
            "https://api.sleeper.com/stats/nba/2027?season_type=regular",
        ):
            r = await http.get(url, headers=UA, timeout=30)
            print(f"\n{url[25:]}: HTTP {r.status_code} {len(r.content):,} bytes")
            if r.status_code == 200:
                d = r.json()
                print(f"  {type(d).__name__} {len(d)}; first {json.dumps(d[0] if isinstance(d, list) and d else d)[:400]}")

        board = (await http.get(f"{SITE}/scoreboard", headers=UA)).json()
        core = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba"
        for ev in (board.get("events") or [])[:2]:
            eid = ev["id"]
            url = f"{core}/events/{eid}/competitions/{eid}/odds/100/propBets?limit=500"
            d = (await http.get(url, headers=UA, timeout=30)).json()
            items = d.get("items") or []
            print(f"\nDraftKings propBets for {ev.get('shortName')}: {d.get('count')} items")
            types = defaultdict(int)
            for it in items:
                types[(it.get("type") or {}).get("name")] += 1
            print(f"  types {dict(types)}")
            for it in items[:2]:
                print(f"  item {json.dumps(it)[:700]}")
            if items:
                ath = (await http.get(items[0]["athlete"]["$ref"], headers=UA, timeout=20)).json()
                print(f"  athlete ref -> {ath.get('displayName')} id {ath.get('id')}")


def positions(roster_payloads):
    out = {}
    for r in roster_payloads:
        for a in r.get("athletes") or []:
            pos = ((a.get("position") or {}).get("abbreviation") or "")[:1]
            out[str(a["id"])] = {"G": "G", "F": "F", "C": "C"}.get(pos, "")
    return out


async def study2():
    async with httpx.AsyncClient(follow_redirects=True) as http:
        teams = (await http.get(f"{SITE}/teams", headers=UA)).json()
        rosters = []
        for t in teams["sports"][0]["leagues"][0]["teams"]:
            rosters.append((await http.get(f"{SITE}/teams/{t['team']['id']}/roster", headers=UA)).json())
        pos = positions(rosters)
        sem = asyncio.Semaphore(12)
        logs = await asyncio.gather(*(gamelog(http, sem, a) for a in pos))
    games = {}
    for aid, payload in logs:
        if payload:
            rows = rows_of(aid, payload, set())
            if len(rows) >= 20:
                games[aid] = rows
    print(f"players {len(games)} · positions {dict((p, sum(1 for a in games if pos.get(a) == p)) for p in 'GFC')}")

    # Team schedule: the days each team played (from any logged player).
    team_days = defaultdict(set)
    for gs in games.values():
        for g in gs:
            if g["team"]:
                team_days[g["team"]].add(g["day"])

    # Opponent allowed by position group, chronologically.
    allowed = defaultdict(lambda: defaultdict(float))  # (opp, day, posgroup) -> stat sums
    for aid, gs in games.items():
        for g in gs:
            for s in ("pts", "reb", "ast", "min"):
                allowed[(g["opp"], g["day"], pos.get(aid, ""))][s] += g[s]

    def factor(opp, day, group, stat):
        mine = [v[stat] / max(v["min"], 1) for (o, d, p), v in allowed.items() if o == opp and p == group and d < day]
        if len(mine) < 8:
            return None
        league = [v[stat] / max(v["min"], 1) for (o, d, p), v in allowed.items() if p == group and d < day]
        return st.mean(mine) / st.mean(league)

    cache = {}

    def f_cached(opp, day, group, stat):
        key = (opp, day[:8] + str(int(day[8:10]) // 7), group, stat)
        if key not in cache:
            cache[key] = factor(opp, day, group, stat)
        return cache[key]

    rows = defaultdict(list)
    for aid, gs in games.items():
        for i, g in enumerate(gs):
            past = gs[:i]
            if len(past) < 10:
                continue
            mpg = st.mean(p["min"] for p in past)
            if mpg < 15:
                continue
            days = sorted(team_days.get(g["team"], ()))
            prev = [d for d in days if d < g["day"]]
            team_rest = (date.fromisoformat(g["day"]) - date.fromisoformat(prev[-1])).days if prev else None
            missed_last = bool(prev) and prev[-1] not in {p["day"] for p in past[-3:]}
            margin = None
            try:
                margin = abs(float(g.get("hs") or 0) - float(g.get("as") or 0)) if g.get("hs") else None
            except ValueError:
                margin = None
            for s in ("pts", "reb", "ast"):
                vals = sorted(p[s] for p in past)
                rows[s].append({
                    "actual": g[s], "avg": st.mean(vals), "median": st.median(vals),
                    "per_min": sum(p[s] for p in past) / sum(p["min"] for p in past),
                    "mpg": mpg, "min": g["min"], "min5": st.mean(p["min"] for p in past[-5:]),
                    "team_rest": team_rest, "returning": missed_last,
                    "f_pos": f_cached(g["opp"], g["day"], pos.get(aid, ""), s), "pos": pos.get(aid, ""),
                    "margin": margin, "star": mpg >= 30,
                })
    for s, rs in rows.items():
        print(f"\n===== {s.upper()} · {len(rs):,} player-games =====")
        over_mean = sum(1 for r in rs if r["actual"] > r["avg"]) / len(rs)
        over_med = sum(1 for r in rs if r["actual"] > r["median"]) / len(rs)
        print(f"Beat his own AVERAGE {pct(over_mean)} · beat his own MEDIAN {pct(over_med)} "
              f"· median below average by {st.mean(r['avg'] - r['median'] for r in rs):.2f} on average")
        withp = [r for r in rs if r["f_pos"] is not None]
        pairs_pos = [(r["per_min"] * r["min5"] * r["f_pos"], r["actual"]) for r in withp]
        pairs_base = [(r["avg"], r["actual"]) for r in withp]
        print(f"Position-matchup model (per-minute x last-5 min x opponent-vs-position): "
              f"{mae(pairs_pos):.2f} vs average {mae(pairs_base):.2f} ({len(withp):,})")
        fs = sorted(r["f_pos"] for r in withp)
        q = [fs[int(len(fs) * k / 5)] for k in range(1, 5)]
        for p in "GFC":
            b = [r for r in withp if r["pos"] == p]
            soft = [r for r in b if r["f_pos"] >= q[3]]
            tough = [r for r in b if r["f_pos"] < q[0]]
            if soft and tough:
                print(f"  {p}: vs softest-20% for his position {st.mean(r['actual'] - r['avg'] for r in soft):+.2f}"
                      f" (beat avg {pct(sum(r['actual'] > r['avg'] for r in soft) / len(soft))}) · toughest "
                      f"{st.mean(r['actual'] - r['avg'] for r in tough):+.2f} "
                      f"(beat {pct(sum(r['actual'] > r['avg'] for r in tough) / len(tough))})")
        print("Team rest (from the team's schedule) and returning from a missed game:")
        for name, pick in (
            ("team back-to-back", lambda r: r["team_rest"] == 1),
            ("team 1 day rest", lambda r: r["team_rest"] == 2),
            ("team 2+ days", lambda r: (r["team_rest"] or 0) >= 3),
            ("player returning (missed one of team's last games)", lambda r: r["returning"]),
        ):
            b = [r for r in rs if pick(r)]
            if b:
                print(f"  {name:52s} {len(b):5d} g · {s} vs avg {st.mean(r['actual'] - r['avg'] for r in b):+.2f}"
                      f" · min vs norm {st.mean(r['min'] - r['mpg'] for r in b):+.2f}")
        bm = [r for r in rs if r["margin"] is not None]
        if bm:
            print("Final margin (blowouts cost starters minutes):")
            for lo, hi in ((0, 6), (6, 12), (12, 20), (20, 99)):
                for who, sel in (("30+ mpg", True), ("15-30 mpg", False)):
                    b = [r for r in bm if lo <= r["margin"] < hi and r["star"] == sel]
                    if b:
                        print(f"  margin {lo:2d}-{hi:2d} {who:9s} {len(b):5d} g · min vs norm "
                              f"{st.mean(r['min'] - r['mpg'] for r in b):+.2f} · {s} vs avg "
                              f"{st.mean(r['actual'] - r['avg'] for r in b):+.2f}")


# --- round 3: a minutes forecast from pregame-knowable signals ---------------


async def study3():
    async with httpx.AsyncClient(follow_redirects=True) as http:
        teams = (await http.get(f"{SITE}/teams", headers=UA)).json()
        rosters = []
        for t in teams["sports"][0]["leagues"][0]["teams"]:
            rosters.append((await http.get(f"{SITE}/teams/{t['team']['id']}/roster", headers=UA)).json())
        pos = positions(rosters)
        sem = asyncio.Semaphore(12)
        logs = await asyncio.gather(*(gamelog(http, sem, a) for a in pos))
    games = {}
    for aid, payload in logs:
        if payload:
            rows = rows_of(aid, payload, set())
            if len(rows) >= 20:
                games[aid] = rows
    played = defaultdict(set)  # (team, day) -> aids who played
    team_days = defaultdict(set)
    for aid, gs in games.items():
        for g in gs:
            played[(g["team"], g["day"])].add(aid)
            team_days[g["team"]].add(g["day"])
    allowed = defaultdict(lambda: defaultdict(float))
    for aid, gs in games.items():
        for g in gs:
            for k in ("pts", "reb", "ast", "min"):
                allowed[(g["opp"], g["day"], pos.get(aid, ""))][k] += g[k]
    cache = {}

    def fpos(opp, day, group, stat):
        key = (opp, day[:8] + str(int(day[8:10]) // 7), group, stat)
        if key not in cache:
            mine = [v[stat] / max(v["min"], 1) for (o, d, p), v in allowed.items()
                    if o == opp and p == group and d < day]
            league = [v[stat] / max(v["min"], 1) for (o, d, p), v in allowed.items() if p == group and d < day]
            cache[key] = st.mean(mine) / st.mean(league) if len(mine) >= 8 else 1.0
        return cache[key]

    # Running minutes norms per player, for "who is a 30+ mpg regular before today".
    def regulars(team, day):
        out = []
        for aid, gs in games.items():
            past = [g for g in gs if g["day"] < day and g["team"] == team]
            if len(past) >= 10 and st.mean(g["min"] for g in past[-15:]) >= 30:
                out.append(aid)
        return out

    reg_cache = {}
    # Fit the minutes adjustments on the first half, test everything on the second.
    rows = []
    for aid, gs in games.items():
        for i, g in enumerate(gs):
            past = gs[:i]
            if len(past) < 10:
                continue
            mpg = st.mean(p["min"] for p in past)
            if mpg < 15:
                continue
            key = (g["team"], g["day"][:8] + str(int(g["day"][8:10]) // 7))
            if key not in reg_cache:
                reg_cache[key] = regulars(g["team"], g["day"])
            regs = [a for a in reg_cache[key] if a != aid]
            out_regs = [a for a in regs if a not in played[(g["team"], g["day"])]]
            prev = sorted(d for d in team_days[g["team"]] if d < g["day"])
            returning = bool(prev) and prev[-1] not in {p["day"] for p in past[-3:]}
            rows.append({
                "day": g["day"], "g": g, "past": past, "mpg": mpg,
                "min5": st.mean(p["min"] for p in past[-5:]),
                "out": len(out_regs), "returning": returning, "pos": pos.get(aid, ""),
            })
    rows.sort(key=lambda r: r["day"])
    half = rows[len(rows) // 2]["day"]
    train = [r for r in rows if r["day"] < half]
    test = [r for r in rows if r["day"] >= half]

    def base_min(r):
        return 0.5 * r["mpg"] + 0.5 * r["min5"]

    adj = {}
    for name, pick in (("out1", lambda r: r["out"] == 1), ("out2", lambda r: r["out"] >= 2),
                       ("returning", lambda r: r["returning"])):
        b = [r for r in train if pick(r)]
        adj[name] = st.mean(r["g"]["min"] - base_min(r) for r in b) if b else 0.0
    print(f"minutes adjustments fitted on games before {half}: "
          + ", ".join(f"{k} {v:+.2f}" for k, v in adj.items()))

    def pred_min(r):
        m = base_min(r)
        if r["out"] == 1:
            m += adj["out1"]
        elif r["out"] >= 2:
            m += adj["out2"]
        if r["returning"]:
            m += adj["returning"]
        return m

    pm = [(pred_min(r), r["g"]["min"]) for r in test]
    pm0 = [(r["mpg"], r["g"]["min"]) for r in test]
    print(f"minutes forecast error on {len(test):,} later games: {mae(pm):.2f} vs his average minutes {mae(pm0):.2f}")
    for stat in ("pts", "reb", "ast"):
        preds = []
        for r in test:
            past = r["past"]
            per_min = sum(p[stat] for p in past) / sum(p["min"] for p in past)
            avg = st.mean(p[stat] for p in past)
            model = per_min * pred_min(r) * fpos(r["g"]["opp"], r["day"], r["pos"], stat)
            preds.append((model, avg, r["g"][stat]))
        print(f"\n{stat.upper()}: model error {mae([(m, a) for m, _, a in preds]):.2f} "
              f"vs season average {mae([(v, a) for _, v, a in preds]):.2f}")
        # Edge buckets: model minus his average -> how often he beats the average
        for lo, hi in ((-99, -3), (-3, -1.5), (-1.5, -0.5), (-0.5, 0.5), (0.5, 1.5), (1.5, 3), (3, 99)):
            scale = 1 if stat == "pts" else 0.35
            b = [(m, v, a) for m, v, a in preds if lo * scale <= m - v < hi * scale]
            if b:
                beat = sum(1 for m, v, a in b if a > v) / len(b)
                print(f"  model {lo * scale:+.1f}..{hi * scale:+.1f} vs his avg: {len(b):5d} g · "
                      f"beat his average {pct(beat)} · actual vs avg {st.mean(a - v for m, v, a in b):+.2f}")


if __name__ == "__main__":
    part = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PROBE_URL", "study")
    parts = {"sources": sources, "study": study, "sources2": sources2, "study2": study2, "study3": study3}
    asyncio.run(parts.get(part, study)())
