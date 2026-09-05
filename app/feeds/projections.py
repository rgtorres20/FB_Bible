"""'26 season projections, scored by each league's own values.

The board's numeric column has been last season's measurement since
Aug 22 -- honest, and not what a draft actually needs. The owner asked
for projections (Aug 25) and the answer until today was that this app
does not have any and will not invent them. It has them now.

**Verified before a line of this was written**, per the rule this repo
keeps paying for. `api.sleeper.com/projections/nfl/2026?season_type=
regular&position[]=...` probed live Aug 25:

    HTTP 200 · 7,040,808 bytes
    list(7658) of dict(17 keys)
      stats: dict(71 keys)     category: 'proj'
      season: '2026'  week: None  game_id: 'season'
      player_id: '4984'         company: 'rotowire'
      last_modified: 1787644261768

Three things that decided the design, all from that probe rather than
from assumption:

- **Season totals, not weekly.** `week: None`, `game_id: 'season'`. No
  summing eighteen fetches, and no pretending a week-1 number is a
  season.
- **The same stat vocabulary as the real stat lines.** pass_yd, rush_td,
  rec, idp_tkl_solo, pts_allow_0 -- so `League.score_player` reads a
  projection exactly as it reads a box score, and a projected total is
  the SAME arithmetic the '25 column already uses. No second scorer, and
  therefore no second place for a league's rules to be wrong.
- **Every group this app's leagues start is covered.** 459 defenders
  carry idp_tkl_solo and 32 teams carry pts_allow_0, which is what makes
  this usable in two IDP leagues and one D/ST league rather than a
  quarterback-and-receiver toy.

Attribution is not decoration: `company` says **rotowire** on every row,
and Sleeper's terms already require crediting them for trending data
(docs/LICENSING.md). Both names ship with the number.

What this is NOT: the app's own opinion. These are Rotowire's forecasts,
relabelled into each league's scoring. The page says whose they are,
because "projected" with no author is the kind of claim this project
does not make.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx

from . import players as players_mod
from . import stats as stats_mod

log = logging.getLogger(__name__)

SEASON = 2026

# Positions asked for explicitly: the endpoint returns nothing without at
# least one, and the set is exactly what the three verified leagues can
# start -- offense, kickers, whole team defenses, and the three IDP groups.
POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF", "LB", "DB", "DL")

URL = (
    "https://api.sleeper.com/projections/nfl/{season}"
    "?season_type=regular&order_by=pts_ppr&" + "&".join(f"position[]={p}" for p in POSITIONS)
)

ATTRIBUTION = "Rotowire via Sleeper"

# Refetched daily. Sleeper asks callers not to hammer them, projections
# move on news rather than by the minute, and `last_modified` on every row
# means staleness is reported rather than guessed at.
REFRESH = timedelta(hours=24)

# A row with no projected games is not a projection -- it is a player the
# forecaster has nothing to say about, and scoring his empty line would
# produce a confident zero.
_MIN_GAMES = 1

# The scorer's own vocabulary, borrowed rather than re-listed. Sleeper
# sends 71 stat keys per row across 7,658 rows; `League.score_player` and
# `score_dst` read these and nothing else, so everything else is weight in
# a Redis blob that is loaded on every page render. Same trim
# `stats.reduce` makes for the same reason, and reusing its list is what
# stops the two drifting into scoring different things.
_KEEP = frozenset(stats_mod.PLAYER_FIELDS) | frozenset(stats_mod.DEFENSE_FIELDS)


async def fetch(client: httpx.AsyncClient | None = None) -> dict:
    """The raw projection rows, or {} on any failure.

    Never raises: a projection column that vanishes for an hour is a
    dash, and a sync that dies takes the injury flags down with it.
    """
    owned = client is None
    client = client or httpx.AsyncClient(
        timeout=60.0, headers={"User-Agent": "FBBible/1.0 (draft prep, daily)"}
    )
    try:
        resp = await client.get(URL.format(season=SEASON))
        resp.raise_for_status()
        rows = resp.json()
        if not isinstance(rows, list):
            log.warning("projections: expected a list, got %s", type(rows).__name__)
            return {}
        return {
            "rows": rows,
            "season": SEASON,
            "fetched_at": datetime.now(UTC).isoformat(),
        }
    except Exception as exc:  # noqa: BLE001 - a missing column is not an outage
        log.warning("projections: fetch failed (%s)", type(exc).__name__)
        return {}
    finally:
        if owned:
            await client.aclose()


def reduce(raw: dict | None) -> dict:
    """{player_id: {"gp": n, **stat line}} plus provenance.

    Keyed by Sleeper's own player_id, which is what the player index is
    keyed by too -- so this joins by id and never by name. Every other
    board in this app matches on a normalised name and has been bitten by
    apostrophes and suffixes for it; here that whole class of bug simply
    does not arise.
    """
    rows = (raw or {}).get("rows") or []
    players: dict[str, dict] = {}
    companies: set[str] = set()
    newest = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        pid = str(row.get("player_id") or "")
        stats = row.get("stats")
        if not pid or not isinstance(stats, dict):
            continue
        games = stats.get("gp") or 0
        if not isinstance(games, int | float) or games < _MIN_GAMES:
            continue
        line = {k: v for k, v in stats.items() if k in _KEEP and isinstance(v, int | float)}
        players[pid] = line
        if row.get("company"):
            companies.add(str(row["company"]))
        stamp = row.get("last_modified") or 0
        if isinstance(stamp, int | float):
            newest = max(newest, int(stamp))
    return {
        "players": players,
        "season": (raw or {}).get("season") or SEASON,
        # Whose forecasts these are, carried from the data rather than
        # written down here -- a hardcoded name would keep saying
        # "rotowire" the day Sleeper switched provider.
        "companies": sorted(companies),
        # Sleeper's own last_modified, in ms. The honest as-of for the
        # numbers, which is not the same as when we fetched them.
        "updated_ms": newest,
        "fetched_at": (raw or {}).get("fetched_at"),
    }


def stale(state: dict | None, now: datetime) -> bool:
    fetched = (state or {}).get("fetched_at")
    if not fetched:
        return True
    try:
        return now - datetime.fromisoformat(fetched) > REFRESH
    except ValueError:
        return True


# --- weekly forecasts for the TD-prop leans --------------------------------
# The Predictions tab's rows are Week 1 touchdown props (vegas.PRED_CAPTION
# says so), so the one week whose forecast is evidence for them is that
# week -- not "the current week", which is a preseason number until
# September.
#
# **Verified before a line of this was written** (probe runs 17 and 19,
# 2026-08-27): the same host serves per-week rows -- HTTP 200, 4.7MB,
# list(7659) with week: 1, season_type: 'regular', company: 'rotowire' --
# and the field census found the three TD fields under the scorer's own
# names with no gaps in coverage: every row projecting pass attempts
# carries pass_td (33 of 33), every rusher rush_td (297 of 297), every
# receiver rec_td (427 of 427). So "field present" is the whole test; a
# missing field means Rotowire has nothing to say, never a hidden zero.
PRED_WEEK = 1

# Since Sep 5 the weekly pull covers the defenders too: both verified
# leagues start eight of them, and the IDP tracker ranks the week's
# projected tacklers under each league's IDP values. The prop clauses
# still only read the three TD fields; `reduce_week` keeps the scorer's
# whole vocabulary, so the stored blob stays a fraction of the download.
WEEK_POSITIONS = ("QB", "RB", "WR", "TE", "LB", "DB", "DL")

WEEK_URL = (
    "https://api.sleeper.com/projections/nfl/{season}/{week}"
    "?season_type=regular&order_by=pts_ppr&" + "&".join(f"position[]={p}" for p in WEEK_POSITIONS)
)

# What a TD prop is settled by, per prop wording. The keys are the page's
# own prop strings (vegas.curated_predictions reads them from the PREDICTIONS
# const), the values are Sleeper's verified field names.
PROP_FIELDS = {
    "Passing TDs": "pass_td",
    "Rushing TDs": "rush_td",
    "Receiving TDs": "rec_td",
}


async def fetch_week(week: int = PRED_WEEK, client: httpx.AsyncClient | None = None) -> dict:
    """One week's projection rows, or {} on any failure. Never raises --
    same contract as `fetch`, for the same reason."""
    owned = client is None
    client = client or httpx.AsyncClient(
        timeout=60.0, headers={"User-Agent": "FBBible/1.0 (draft prep, daily)"}
    )
    try:
        resp = await client.get(WEEK_URL.format(season=SEASON, week=week))
        resp.raise_for_status()
        rows = resp.json()
        if not isinstance(rows, list):
            log.warning("week projections: expected a list, got %s", type(rows).__name__)
            return {}
        return {
            "rows": rows,
            "season": SEASON,
            "week": week,
            "fetched_at": datetime.now(UTC).isoformat(),
        }
    except Exception as exc:  # noqa: BLE001 - a missing clause is not an outage
        log.warning("week projections: fetch failed (%s)", type(exc).__name__)
        return {}
    finally:
        if owned:
            await client.aclose()


def reduce_week(raw: dict | None) -> dict:
    """{player_id: {scorer's stat line for the week}} plus provenance, same
    joins-by-id rule as `reduce` and for the same reason.

    Kept the whole `_KEEP` vocabulary since Sep 3, not just the three TD
    fields: the TD-prop clauses only ever read those three, but ranking a
    slate's games by projected fantasy points (the schedule tab's game
    stack) needs the yards, receptions and completions the league scorer
    multiplies -- the same line `reduce` keeps for the season forecast,
    one week at a time. The stored blob grows from three keys a player to
    the scorer's ~25; still a fraction of the 4.7MB Sleeper sends.
    """
    rows = (raw or {}).get("rows") or []
    keep = _KEEP
    players: dict[str, dict] = {}
    companies: set[str] = set()
    newest = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        pid = str(row.get("player_id") or "")
        stats = row.get("stats")
        if not pid or not isinstance(stats, dict):
            continue
        line = {k: v for k, v in stats.items() if k in keep and isinstance(v, int | float)}
        if not line:
            continue
        players[pid] = line
        if row.get("company"):
            companies.add(str(row["company"]))
        stamp = row.get("last_modified") or 0
        if isinstance(stamp, int | float):
            newest = max(newest, int(stamp))
    return {
        "players": players,
        "season": (raw or {}).get("season") or SEASON,
        "week": (raw or {}).get("week") or PRED_WEEK,
        "companies": sorted(companies),
        "updated_ms": newest,
        "fetched_at": (raw or {}).get("fetched_at"),
    }


def week_stale(state: dict | None, now: datetime) -> bool:
    """Same daily budget as the season forecast, same reasoning."""
    return stale(state, now)


def td_forecasts(
    state: dict | None, preds: list[dict], name_to_id: dict[str, str] | None
) -> dict[str, str]:
    """{prediction row name: one labelled forecast sentence}.

    The number is Rotowire's, the label says so, and the lean and the
    confidence are never touched -- the same contract as the AI check
    clause. A player the forecast does not cover, a prop this table does
    not map, or a name the index cannot resolve all produce NO clause
    rather than a zero: absent is a fact, zero is a claim.
    """
    players = (state or {}).get("players") or {}
    week = (state or {}).get("week") or PRED_WEEK
    if not players or not name_to_id:
        return {}
    label = source_label(state)
    out: dict[str, str] = {}
    for pred in preds:
        field = PROP_FIELDS.get(pred.get("prop") or "")
        if not field:
            continue
        # match_key is THE join key -- the same one name_to_id was built
        # with (scorecard.name_index), so the two sides cannot disagree
        # on suffixes or apostrophes.
        key = players_mod.match_key(pred.get("name") or "")
        line = players.get(str(name_to_id.get(key) or ""))
        if not line or field not in line:
            continue
        value = line[field]
        out[pred["name"]] = f"Wk {week} forecast: {value:.1f} {pred['prop'].lower()} ({label})."
    return out


def as_of(state: dict | None) -> str:
    """When the FORECASTS were last revised, not when we fetched them.

    Two different timestamps, and the useful one is Sleeper's. A daily
    refetch of numbers nobody has revised in a week is fresh by one
    measure and a week old by the one that matters.
    """
    ms = (state or {}).get("updated_ms") or 0
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d")


def source_label(state: dict | None) -> str:
    """Who to credit, from the data. Falls back to the verified default."""
    companies = (state or {}).get("companies") or []
    if not companies:
        return ATTRIBUTION
    return " / ".join(c.title() for c in companies) + " via Sleeper"
