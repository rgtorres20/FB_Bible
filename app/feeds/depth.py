"""Depth charts measured from last season's usage, and who is next up.

Two owner asks, Aug 21, that turn out to be the same question:

  * "Backup running list / usage splits not live estimates" — the
    handcuff table's snap and carry shares were curated guesses.
  * "Is there a way to search for latest post of sleepers or backups
    (need to be picked up after injuries to starters)?"

Both need one thing the app already had and never joined up: Sleeper's
'25 per-player usage, which the stats reducer has been storing since
August (`rush_att`, `rec_tgt`, `rush_rz_att`, `off_snp`/`tm_off_snp`).
Order a team's players at a position by that usage and you have a depth
chart that was measured rather than asserted; take the man behind an
injured starter and you have the pickup.

Honesty rules, the same ones the rest of the app runs on:

  * The numbers are **last season's**, and every surface says so. A depth
    chart from '25 usage is a prior, not a promise about Week 1 — rookies
    and free-agent signings have no usage at all, and the rows say that
    rather than showing a zero that reads like a measurement.
  * The **injury flags are live** (Sleeper's player index, refreshed each
    sync) and the wire post beside each name is the real latest item that
    mentions them. Nothing here is generated prose.
  * A backup nobody can name is not a find. Rows carry the Sleeper draft
    rank so "widely rostered already" is visible rather than implied.
"""

from __future__ import annotations

import re

from . import players as players_mod

# What counts as "this starter is not playing". Sleeper's own vocabulary,
# now owned by the kernel because the draft board needs the same answer
# for its badge. Questionable is deliberately outside it -- a questionable
# starter is not a pickup trigger, and treating it as one would cry wolf
# every week.
from .players import OUT_FLAGS  # noqa: E402

# Which measured field means "opportunity" at each position. A back's
# workload is carries plus targets; a receiver's is targets; a
# quarterback's is attempts; a defender's is tackles.
#
# Defenders were left out entirely until Aug 22, which meant the pickup
# board ignored a third of the roster: both verified IDP leagues start
# EIGHT defensive players (docs/LEAGUES.md), and an injured starting
# linebacker is exactly as much of a hole as an injured running back.
# Tackles are the right measure for the same reason the IDP board says
# so -- solo plus assist volume dominates that scoring.
_OPPORTUNITY = {
    "RB": ("rush_att", "rec_tgt"),
    "FB": ("rush_att", "rec_tgt"),
    "WR": ("rec_tgt",),
    "TE": ("rec_tgt",),
    "QB": ("pass_att",),
    "DB": ("idp_tkl_solo", "idp_tkl_ast"),
    "LB": ("idp_tkl_solo", "idp_tkl_ast"),
    "DL": ("idp_tkl_solo", "idp_tkl_ast"),
}

SKILL_POSITIONS = ("QB", "RB", "WR", "TE")

# Defenders are grouped the way a league starts them -- DB/LB/DL -- not
# by their listed position. A league rosters linebackers, not MIKEs and
# WILLs separately, so the man behind an injured LB is the next LB.
IDP_GROUPS = ("DB", "LB", "DL")


def opportunity(entry: dict | None, position: str) -> float:
    if not entry:
        return 0.0
    return sum(entry.get(f, 0) or 0 for f in _OPPORTUNITY.get(position, ("rec_tgt",)))


def usage(entry: dict | None) -> dict:
    """One player's measured '25 workload, or empty when there is none.

    Empty is a real answer -- a rookie has no last season -- and the
    caller renders it as "no '25 usage" rather than as zeros.
    """
    if not entry:
        return {}
    solo = entry.get("idp_tkl_solo", 0) or 0
    assisted = entry.get("idp_tkl_ast", 0) or 0
    if solo or assisted:
        # A defender's workload is tackles, and reporting his carries
        # would be reporting zeros about the wrong thing.
        return {
            "gp": entry.get("gp"),
            "idp_tkl_solo": solo,
            "idp_tkl_ast": assisted,
            "idp_sack": entry.get("idp_sack", 0) or 0,
            "idp_int": entry.get("idp_int", 0) or 0,
            "idp_pass_def": entry.get("idp_pass_def", 0) or 0,
        }
    carries = entry.get("rush_att", 0) or 0
    targets = entry.get("rec_tgt", 0) or 0
    touches = carries + targets
    snaps, team_snaps = entry.get("off_snp", 0) or 0, entry.get("tm_off_snp", 0) or 0
    out = {
        "gp": entry.get("gp"),
        "rush_att": carries,
        "rec_tgt": targets,
        "rz_att": entry.get("rush_rz_att", 0) or 0,
        "rz_tgt": entry.get("rec_rz_tgt", 0) or 0,
    }
    if touches:
        # The split the handcuff table used to guess at: of everything
        # this player was given, how much came on the ground.
        out["rush_share"] = round(100 * carries / touches)
    if snaps and team_snaps:
        out["snap_share"] = round(100 * snaps / team_snaps)
    return out


def _players(index: dict | None) -> dict:
    return (index or {}).get("players") or {}


def chart(index: dict | None, stats_state: dict | None) -> dict[tuple[str, str], list[dict]]:
    """{(team, position): [players, most opportunity first]}.

    Ordered by measured '25 opportunity, with Sleeper's draft rank as the
    tiebreak -- and as the only ordering available for anyone who did not
    play last season. Ranked players only: the index carries every active
    body in the league, and a third-string tight end nobody has heard of
    is noise on every surface this feeds.
    """
    stats = ((stats_state or {}).get("players") or {}) if stats_state else {}
    out: dict[tuple[str, str], list[dict]] = {}

    for pid, player in _players(index).items():
        # A defender competes for his GROUP's slots, so that is the depth
        # chart he belongs on -- his listed position (MIKE, WILL, CB, FS)
        # is finer than any league rosters.
        group = player.get("idp")
        position = group or (player.get("position") or "").upper()
        team = player.get("team") or ""
        if position not in (*SKILL_POSITIONS, *IDP_GROUPS) or not team or player.get("dst"):
            continue
        entry = stats.get(pid)
        rank = player.get("rank")
        if rank is None and not entry:
            continue
        out.setdefault((team, position), []).append(
            {
                "id": pid,
                "name": player.get("name") or "",
                "position": position,
                "team": team,
                "injury": (player.get("injury_status") or "").strip(),
                "rank": rank,
                "opportunity": opportunity(entry, position),
                "usage": usage(entry),
                # Sleeper's live depth chart (Sep 5) and practice report,
                # absent when Sleeper has nothing to say.
                "depth_order": player.get("depth_order"),
                "practice": player.get("practice") or "",
            }
        )

    # Sleeper's published depth order leads when it is there -- it sees a
    # rookie, a trade and a camp battle that last season's touches cannot.
    # Measured '25 opportunity breaks ties and orders anyone Sleeper has
    # not slotted, and rank is the last resort for a man with neither.
    for players in out.values():
        players.sort(
            key=lambda p: (
                p["depth_order"] if isinstance(p["depth_order"], int) else 10**6,
                -p["opportunity"],
                p["rank"] if p["rank"] is not None else 10**6,
            )
        )
    return out


def is_out(player: dict) -> bool:
    return player.get("injury", "") in OUT_FLAGS


def next_man_up(index: dict | None, stats_state: dict | None) -> list[dict]:
    """Starters who are not playing, and the player behind them.

    A "starter" here is whoever led that team and position in '25
    opportunity -- measured, not a published depth chart, because no free
    source publishes one. The replacement is the next man at the same
    team and position who is not himself flagged out.

    Ordered by how much work is actually coming loose: a lead back's
    carries are a pickup, a fourth receiver's are not.

    **A room where everyone is hurt still reports.** Until Aug 21 this
    skipped any room with no healthy body behind the starter -- which is
    exactly the room worth knowing about, and the silence was
    indistinguishable from "nobody is injured here". It now names the
    next man whatever his own flag says and marks the row `room_all_out`,
    so the surface can show the flags instead of showing nothing.

    The one room still skipped is the one with literally nobody behind
    the starter: there is no pickup to name, and a row naming no player
    would be a row about nothing.
    """
    out = []
    for (team, position), players in chart(index, stats_state).items():
        if not players:
            continue
        starter = players[0]
        if not is_out(starter):
            continue
        behind = players[1:]
        if not behind:
            continue
        healthy = next((p for p in behind if not is_out(p)), None)
        replacement = healthy if healthy is not None else behind[0]
        out.append(
            {
                "team": team,
                "position": position,
                "starter": starter,
                "replacement": replacement,
                # Every body behind the starter is flagged too. The row is
                # still worth showing -- more so, not less -- but it is a
                # vacancy rather than a pickup, and the caller has to be
                # able to say which.
                "room_all_out": healthy is None,
                # What is on the table: the starter's own '25 workload,
                # which is the honest measure of the vacancy rather than
                # a projection of what the backup will do with it.
                "vacated": starter["opportunity"],
                "depth": [p["name"] for p in players[:4]],
            }
        )
    out.sort(key=lambda r: r["vacated"], reverse=True)
    return out


def backups(
    index: dict | None,
    stats_state: dict | None,
    position: str = "RB",
    limit: int = 40,
) -> list[dict]:
    """The handcuff list: every team's second man at one position.

    This is the measured replacement for the curated snap-and-carry
    guesses the page shipped with. The judgement (is the starter fragile,
    is this a free add) is not here and is not computable -- it stays the
    owner's, on the page.
    """
    rows = []
    for (team, pos), players in chart(index, stats_state).items():
        if pos != position or len(players) < 2:
            continue
        starter, backup = players[0], players[1]
        rows.append(
            {
                "team": team,
                "position": pos,
                "name": backup["name"],
                "id": backup["id"],
                "injury": backup["injury"],
                "rank": backup["rank"],
                "usage": backup["usage"],
                # The position-aware workload `chart` already measured:
                # carries plus targets at RB, targets at WR and TE, pass
                # attempts at QB. Carried through so the sort below does
                # not have to pick a field and get it wrong.
                "opportunity": backup["opportunity"],
                "starter": starter["name"],
                "starter_out": is_out(starter),
                "starter_usage": starter["usage"],
                # How much of the team's work at this position the starter
                # took. The higher it is, the more a handcuff is worth.
                "starter_share": (
                    round(100 * starter["opportunity"] / total)
                    if (total := sum(p["opportunity"] for p in players))
                    else None
                ),
            }
        )
    # Ordered by the backup's own opportunity at his own position. This
    # sorted on rush_att until Aug 21, which is right at RB and silently
    # wrong everywhere else: every receiver's key was 0, so the WR board
    # came back in index order and read as a ranking. Rank breaks ties,
    # including the all-zero case of a room where nobody played last year.
    rows.sort(key=lambda r: (-r["opportunity"], r["rank"] if r["rank"] is not None else 10**6))
    return rows[:limit]


def latest_mentions(items: list[dict] | None, ids: set[str]) -> dict[str, dict]:
    """The newest wire item mentioning each of these players.

    Items already carry their tagged players (`app/feeds/players.py`), so
    this is a join rather than a search -- and it returns the real item,
    never a summary of one.
    """
    found: dict[str, dict] = {}
    for item in items or []:
        for tagged in item.get("players") or []:
            pid = tagged.get("id")
            if pid in ids and pid not in found:
                found[pid] = item
    return found


# --- the handcuff table, measured (owner, Aug 25) ---------------------------

_CUFF_BLOCK = re.compile(r"const CUFFS = \[.*?\n\];", re.S)
_CUFF_NAME = re.compile(r'\{ name: "([^"]+)"')
_CUFF_FIELDS = re.compile(r'(rush: )\d+(, split: )"[^"]*"(, gl: )"[^"]*"(, glNote: )"[^"]*"')


def cuff_usage(index: dict | None, stats_state: dict | None, names: list[str]) -> dict[str, dict]:
    """{page name: measured '25 usage} for the handcuff table's players.

    The same `usage()` every other measured surface reads. Absent means
    the stats do not cover him, and the row says so rather than keeping a
    number nobody can source.
    """
    # `by_name` maps a name to an ID, not to a record (players.build_index).
    # Reading `.get("id")` off it raised AttributeError on every real page
    # render -- and because main.py wraps the whole overlay pass in one
    # `except Exception`, it also silently took the Team-intel usage read
    # down with it. Caught live Aug 26, not by any test: every fixture here
    # had been built to the shape the docstring wrongly claimed.
    lookup = (index or {}).get("by_name") or {}
    lines = ((stats_state or {}).get("players") or {}) if stats_state else {}
    out: dict[str, dict] = {}
    for name in names:
        pid = lookup.get(players_mod.match_key(name))
        if not pid:
            continue
        measured = usage(lines.get(str(pid)))
        if measured.get("rush_att") or measured.get("rec_tgt"):
            out[name] = measured
    return out


def inject_cuffs(html: str, index: dict | None, stats_state: dict | None) -> tuple[str, int]:
    """Replace the handcuff table's invented usage with measured '25.

    Owner, Aug 25, after being shown where that list comes from. Its 32
    rows carried "78% rush · 22% routes" and "24 GL carries" with no
    source behind any of them -- numbers shaped like measurements that
    nobody had measured. docs/STALE_DATA.md has named this the remaining
    step since Aug 21, because `depth.usage()` already computes the real
    versions for /app/nextup and nothing had joined them up.

    Only the four measured fields move. `starter`, `risk`, `cost` and
    `why` are the owner's judgement about who is worth a late pick, and
    that is the part of this table worth keeping.

    ONE relabel, and it matters: the table said "GL carries ... inside the
    5" and Sleeper counts red-zone attempts, inside the 20. Different
    numbers. Writing a red-zone figure under a goal-line label would swap
    an unsourced number for a mislabelled one, so the label moves with the
    data -- the same call the Team-intel usage read made in August.

    A player the stats do not cover keeps no number at all: the bar reads
    0 and the cell says "no '25 usage", which is the honest answer for a
    rookie and the one /app/nextup already gives.
    """
    block = _CUFF_BLOCK.search(html)
    if not block:
        return html, 0
    names = _CUFF_NAME.findall(block.group(0))
    measured = cuff_usage(index, stats_state, names)
    if not measured:
        return html, 0

    rows = block.group(0).split("\n")
    out_rows: list[str] = []
    changed = 0
    for row in rows:
        found = _CUFF_NAME.search(row)
        if not found:
            out_rows.append(row)
            continue
        stats = measured.get(found.group(1))
        if not stats:
            # A lambda, not a replacement template: a template would put
            # a backslash next to the apostrophe in "'25" and emit
            # "no \'25 usage" into a double-quoted JS string. Legal, and
            # visible to anyone reading the page source.
            replaced = _CUFF_FIELDS.sub(
                lambda m: (
                    f"{m.group(1)}0"
                    f'{m.group(2)}"no \'25 usage"'
                    f'{m.group(3)}"\u2014"'
                    f'{m.group(4)}"not in the \'25 stats"'
                ),
                row,
            )
        else:
            share = stats.get("rush_share")
            split = (
                f"{share}% rush · {100 - share}% routes"
                if isinstance(share, int)
                else "no '25 usage"
            )
            replaced = _CUFF_FIELDS.sub(
                lambda m, s=stats, sp=split, sh=share: (
                    f"{m.group(1)}{sh if isinstance(sh, int) else 0}"
                    f'{m.group(2)}"{sp}"'
                    f'{m.group(3)}"{s.get("rz_att", 0)} RZ carries"'
                    f'{m.group(4)}"inside the 20, \'25 · measured"'
                ),
                row,
            )
        if replaced != row:
            changed += 1
        out_rows.append(replaced)

    return html.replace(block.group(0), "\n".join(out_rows), 1), changed
