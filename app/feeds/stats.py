"""Sleeper 2025 season stats: team usage aggregates, measured, never assumed.

/v1/stats/nfl/regular/2025 (probed live Aug 16: HTTP 200, 8,243 keys, ~1.9MB)
holds three populations in one dict:

  - 8,179 numeric keys       -- per-player season lines
  - 32 team codes ("HOU")    -- team DEFENSE/special-teams fantasy aggregates
  - 32 "TEAM_XXX" keys       -- team OFFENSE aggregates (pass_att, rush_att,
                                red-zone and goal-to-go splits, snaps)

The design rule this module exists to enforce: the probe that verified the
endpoint found its richest entry was a team aggregate, so per-player field
coverage could not be assumed -- and measured, it is genuinely sparse
(pass_att: 128 players; rush_att: 367; rec_tgt: 534; off_snp: 947 -- of
8,179). So `reduce()` counts holders per field into `coverage`, the stored
state carries those counts, and every consumer gates on them instead of
trusting a field to be there. `usage_reads()` returns None -- not a partial
map -- unless all 32 teams carry the fields it needs.

The season is final, so the numbers never change; the fetch is a weekly
re-check, not a poll. Sleeper requires attribution wherever this surfaces.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx

log = logging.getLogger(__name__)

STATS_URL = "https://api.sleeper.app/v1/stats/nfl/regular/2025"
SEASON = 2025

# Final-season data is static; a weekly refetch only guards against the
# store being flushed or the reduction shape changing.
REFRESH = timedelta(days=7)

# Team offense fields the Team-intel usage reads consume, plus the goal-to-go
# pair kept for future surfaces (Sleeper reports g2g attempts/conversions but
# no run/pass split inside them, so "goal-line run rate" cannot be computed
# honestly -- red-zone run share is the closest real number).
TEAM_FIELDS = (
    "gp",
    "pass_att",
    "rush_att",
    "pass_rz_att",
    "rush_rz_att",
    "rz_att",
    "rz_conv",
    "g2g_att",
    "g2g_conv",
    "pass_yd",
    "rush_yd",
)

# Per-player usage: snap share (off_snp / tm_off_snp), carries, targets and
# their red-zone cuts -- what handcuff splits and role reads are made of.
# The idp_* block is what the owner's leagues score defenders on
# (docs/LEAGUES.md); every name verified against the live dump's field
# census 2026-08-20 (probe run 5: idp_tkl_solo 1124 holders, idp_sack 440,
# idp_int 221, idp_pass_def 578, ...). Coverage counts still gate consumers.
PLAYER_FIELDS = (
    "gp",
    "off_snp",
    "tm_off_snp",
    "rush_att",
    "rush_rz_att",
    "rush_yd",
    "rush_td",
    "rec_tgt",
    "rec",
    "rec_rz_tgt",
    "rec_yd",
    "rec_td",
    "pass_att",
    "pass_rz_att",
    "def_snp",
    "tm_def_snp",
    "idp_tkl_solo",
    "idp_tkl_ast",
    "idp_tkl",
    "idp_tkl_loss",
    "idp_qb_hit",
    "idp_sack",
    "idp_int",
    "idp_int_ret_yd",
    "idp_pass_def",
    "idp_ff",
    "idp_fum_rec",
    "idp_fum_ret_yd",
    "idp_def_td",
    "idp_safe",
    "idp_blk_kick",
)

# Bump when PLAYER_FIELDS / TEAM_FIELDS change shape: stale() then refetches
# even inside the weekly window, so a deploy that adds fields does not wait
# a week for the store to carry them. v2: the idp_* block.
STATS_VERSION = 2

# Sleeper says WAS; every const in the page says WSH.
_PAGE_CODES = {"WAS": "WSH"}

_TEAM_PREFIX = "TEAM_"


async def fetch(client: httpx.AsyncClient | None = None) -> dict:
    """Download the season dump and reduce it to the stored state."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(
            timeout=90.0,
            headers={"User-Agent": "FBBible/1.0 (personal fantasy tool, weekly)"},
        )
    try:
        response = await client.get(STATS_URL)
        response.raise_for_status()
        raw = response.json()
    finally:
        if own_client:
            await client.aclose()
    return reduce(raw)


def reduce(raw: dict) -> dict:
    """Reduce the 1.9MB dump to team offense aggregates, player usage lines
    and the per-field coverage counts consumers gate on.

    Players are kept only when they show offensive usage (a carry, a target
    or a pass attempt) -- 603 of 8,179 at probe time -- which keeps the
    stored state ~80KB instead of megabytes.
    """
    teams: dict[str, dict] = {}
    players: dict[str, dict] = {}
    coverage_players: dict[str, int] = dict.fromkeys(PLAYER_FIELDS, 0)
    coverage_teams: dict[str, int] = dict.fromkeys(TEAM_FIELDS, 0)
    n_players = n_team_offense = n_team_defense = 0

    for key, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        if key.startswith(_TEAM_PREFIX):
            n_team_offense += 1
            code = key[len(_TEAM_PREFIX) :]
            code = _PAGE_CODES.get(code, code)
            kept = {f: entry[f] for f in TEAM_FIELDS if isinstance(entry.get(f), int | float)}
            for f in kept:
                coverage_teams[f] += 1
            if kept:
                teams[code] = kept
        elif key.isdigit():
            n_players += 1
            for f in PLAYER_FIELDS:
                if isinstance(entry.get(f), int | float):
                    coverage_players[f] += 1
            usage_gate = ("rush_att", "rec_tgt", "pass_att", "idp_tkl", "idp_tkl_solo")
            if any(entry.get(f) for f in usage_gate):
                players[key] = {
                    f: entry[f] for f in PLAYER_FIELDS if isinstance(entry.get(f), int | float)
                }
        else:
            n_team_defense += 1  # bare team codes: DEF/ST fantasy aggregates

    return {
        "fetched_at": datetime.now(UTC).isoformat(),
        "v": STATS_VERSION,
        "season": SEASON,
        "teams": teams,
        "players": players,
        "coverage": {
            "players": coverage_players,
            "team_offense": coverage_teams,
        },
        "populations": {
            "players": n_players,
            "team_offense": n_team_offense,
            "team_defense": n_team_defense,
        },
    }


def stale(state: dict | None, now: datetime) -> bool:
    """Whether the sync should refetch: absent, unparseable, a week old, or
    reduced by an older extractor (missing fields this code expects)."""
    if not state or not state.get("teams"):
        return True
    if state.get("v") != STATS_VERSION:
        return True
    try:
        fetched = datetime.fromisoformat(state.get("fetched_at") or "")
    except ValueError:
        return True
    if fetched.tzinfo is None:
        return True
    return now - fetched > REFRESH


# --- Team usage reads ------------------------------------------------------

_USAGE_FIELDS = ("pass_att", "rush_att", "pass_rz_att", "rush_rz_att")
_ALL_TEAMS = 32


def usage_reads(state: dict | None) -> dict[str, dict] | None:
    """{code: {"pass": int, "rz_run": int}} for every team, or None.

    All-or-nothing on purpose: a map with 29 real teams and 3 absent ones
    would leave the page's fabricated fallback numbers standing next to real
    ones with no way to tell them apart -- exactly the false positive the
    project rules ban. Coverage is checked against the entries themselves,
    not assumed from the fetch having succeeded.
    """
    teams = (state or {}).get("teams") or {}
    if len(teams) < _ALL_TEAMS:
        return None
    reads: dict[str, dict] = {}
    for code, entry in teams.items():
        if not all(entry.get(f) for f in _USAGE_FIELDS):
            return None
        plays = entry["pass_att"] + entry["rush_att"]
        rz_plays = entry["pass_rz_att"] + entry["rush_rz_att"]
        reads[code] = {
            "pass": round(100 * entry["pass_att"] / plays),
            "rz_run": round(100 * entry["rush_rz_att"] / rz_plays),
        }
    return reads


# --- Serve-time injection into the page ------------------------------------
#
# Same no-fork pattern as board/vegas: the committed consts are estimates;
# when the stored season aggregates cover all 32 teams they are replaced in
# the served response only. Every anchor must match or the original page is
# returned untouched -- a design-project resync that changes a shape misses
# cleanly rather than serving a half-patched page.

import json as _json  # noqa: E402  (stdlib, placed by the code that uses it)
import re as _re  # noqa: E402

_PASSRATE = _re.compile(r"const PASSRATE = \{[^}]*\};")
_GLRUN = _re.compile(r"const GLRUN = \{[^}]*\};")
_TEAM_SPLIT = _re.compile(r"const TEAM_SPLIT = \{[^}]*\};")

LIVE_MARKER = "// FB live usage: Sleeper '25 season"

# The committed labels say "GL x% run" over goal-line estimates. The live
# number is red-zone run share (Sleeper carries no run/pass split inside
# goal-to-go), so the label must change with the data or it becomes a lie
# with better numbers: the served label reads "RZ 50% run share ('25)",
# naming both the stat and its vintage. The color threshold moves from the
# goal-line scale (68% marked run-heavy) to the red-zone scale (55%; live
# range 33-64).
_RELABELS = (
    ('"GL " + (TEAM_SPLIT', '"RZ " + (TEAM_SPLIT'),
    ('"GL " + (GLRUN', '"RZ " + (GLRUN'),
    ('[1] + "% run",', '[1] + "% run share (\'25)",'),
    ('(GLRUN[tm.code] || 62) + "% run",', '(GLRUN[tm.code] || 62) + "% run share (\'25)",'),
    ("(GLRUN[tm.code] || 62) >= 68", "(GLRUN[tm.code] || 0) >= 55"),
)


def _const(name: str, value: dict) -> str:
    body = _json.dumps(value, separators=(",", ":"), sort_keys=True)
    return f"const {name} = {body}; {LIVE_MARKER}"


def inject(html: str, state: dict | None) -> tuple[str, bool]:
    """Swap the curated PASSRATE / GLRUN / TEAM_SPLIT estimates for the
    measured '25 aggregates. Returns (page, injected?)."""
    reads = usage_reads(state)
    if reads is None:
        return html, False

    passrate = {code: r["pass"] for code, r in reads.items()}
    rz_run = {code: r["rz_run"] for code, r in reads.items()}
    split = {code: [r["pass"], r["rz_run"]] for code, r in reads.items()}

    patched = html
    for pattern, name, value in (
        (_PASSRATE, "PASSRATE", passrate),
        (_GLRUN, "GLRUN", rz_run),
        (_TEAM_SPLIT, "TEAM_SPLIT", split),
    ):
        replacement = _const(name, value)
        patched, count = pattern.subn(lambda _m, r=replacement: r, patched, count=1)
        if not count:
            return html, False

    for old, new in _RELABELS:
        if old not in patched:
            return html, False
        patched = patched.replace(old, new, 1)
    return patched, True
