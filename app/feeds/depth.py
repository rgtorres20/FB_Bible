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

# What counts as "this starter is not playing". Sleeper's own vocabulary;
# Questionable is deliberately absent -- a questionable starter is not a
# pickup trigger, and treating it as one would cry wolf every week.
OUT_FLAGS = {"Out", "IR", "PUP", "Sus", "NA", "Doubtful", "DNR"}

# Which measured field means "opportunity" at each position. A back's
# workload is carries plus targets; a receiver's is targets; a
# quarterback's is attempts.
_OPPORTUNITY = {
    "RB": ("rush_att", "rec_tgt"),
    "FB": ("rush_att", "rec_tgt"),
    "WR": ("rec_tgt",),
    "TE": ("rec_tgt",),
    "QB": ("pass_att",),
}

SKILL_POSITIONS = ("QB", "RB", "WR", "TE")


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
        position = (player.get("position") or "").upper()
        team = player.get("team") or ""
        if position not in SKILL_POSITIONS or not team or player.get("dst"):
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
            }
        )

    for players in out.values():
        players.sort(
            key=lambda p: (-p["opportunity"], p["rank"] if p["rank"] is not None else 10**6)
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
