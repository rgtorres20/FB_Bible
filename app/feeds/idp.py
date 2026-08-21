"""The IDP draft board: defenders scored with each league's own settings.

Both of the owner's leagues start 8 defensive players (docs/LEAGUES.md):
NDDPL starts 4 DB + 4 LB (no DL slot at all); RED_EYE starts 4 D -- any
defender -- plus 4 DB. Market IDP rankings assume generic scoring, so this
board scores the '25 season totals with each league's *verified* values
instead: NDDPL pays 3 a sack and 2 an interception, RED_EYE pays 2 and 3,
and both pay tackles, passes defensed, forced and recovered fumbles,
defensive TDs, safeties, blocks, and turnover-return yardage (20 yds/pt in
NDDPL, 10 in RED_EYE).

Honesty rules, same as everywhere: the numbers are last season's finals
wearing that label -- a draft-prep ranking, not a projection; every stat
field was verified against the live dump's field census before being
trusted (probe run 5, 2026-08-20); and when the stored stats predate the
IDP fields the page says so instead of rendering an empty table as if no
defender mattered.
"""

from __future__ import annotations

import html as html_mod
from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from .. import leagues as leagues_mod

CENTRAL = ZoneInfo("America/Chicago")

TOP = 150

# The per-event values and the startable groups both live in
# `app.leagues` now -- one canonical description per league, so a user
# editing their settings changes scoring and eligibility together
# instead of leaving the two halves to be kept in step by hand.
BOARD_LEAGUES = leagues_mod.defaults()

_STYLE = """
body { font-family: Georgia, 'Times New Roman', serif; margin: 24px;
       color: #16234A; background: #F5F1E6; }
h1 { font-size: 22px; margin: 0 0 2px; }
.sub { font-size: 12px; color: #5a5a4f; margin-bottom: 14px; max-width: 720px; }
table { border-collapse: collapse; width: 100%; font-size: 11.5px; }
th { text-align: left; border-bottom: 2px solid #16234A; padding: 3px 6px;
     font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase; }
td { padding: 3px 6px; border-bottom: 1px solid #ddd6c4; }
td.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.grp { font-weight: bold; }
.na { color: #8a8a7c; }
@media print { body { background: #fff; margin: 8mm; } }
"""


def score(entry: dict, league: leagues_mod.League) -> float:
    """One player's '25 total under one league's IDP settings."""
    return league.score_idp(entry)


def has_idp_stats(stats_state: dict | None) -> bool:
    """Whether the stored season stats were reduced with the IDP fields."""
    coverage = ((stats_state or {}).get("coverage") or {}).get("players") or {}
    return bool(coverage.get("idp_tkl_solo"))


def rows(
    index: dict | None,
    stats_state: dict | None,
    top: int = TOP,
    board_leagues: Sequence[leagues_mod.League] | None = None,
) -> list[dict]:
    """Defenders the index knows, scored per league, best first.

    Ordered by the best of the league scores; position ranks are computed
    within each league's startable groups only, so a DL shows a RED_EYE
    rank and an explicit dash for NDDPL rather than a fake number. Each
    league contributes two keys named after itself -- `nddpl` and
    `nddpl_rank` -- so a user-defined league lands in the same rows
    without the callers learning a new shape.

    `top` widens the cut for consumers that need per-group depth the
    board's page cut cannot promise (the mock draft room must seat
    12 teams x 4 DBs).
    """
    board = list(board_leagues if board_leagues is not None else BOARD_LEAGUES)
    players = (index or {}).get("players") or {}
    stats = ((stats_state or {}).get("players") or {}) if stats_state else {}

    out = []
    for pid, player in players.items():
        group = player.get("idp")
        entry = stats.get(pid)
        if not group or not entry:
            continue
        scores = {lg.key: lg.score_idp(entry) for lg in board}
        if all(v <= 0 for v in scores.values()):
            continue
        row = {
            "id": pid,
            "name": player.get("name") or "",
            "position": player.get("position") or "",
            "group": group,
            "team": player.get("team") or "FA",
            "injury": (player.get("injury_status") or "").strip(),
            "gp": entry.get("gp"),
            "solo": entry.get("idp_tkl_solo", 0),
            "ast": entry.get("idp_tkl_ast", 0),
            "sack": entry.get("idp_sack", 0),
            "int": entry.get("idp_int", 0),
            "pd": entry.get("idp_pass_def", 0),
        }
        # A group the league cannot start is a dash, not a number: the
        # score would be arithmetically fine and practically a lie.
        for lg in board:
            row[lg.key] = scores[lg.key] if group in lg.idp_groups else None
        out.append(row)

    out.sort(key=lambda r: max((r[lg.key] or 0) for lg in board), reverse=True)

    for lg in board:
        counters: dict[str, int] = {}
        ordered = sorted(
            (r for r in out if r[lg.key] is not None),
            key=lambda r, k=lg.key: r[k],
            reverse=True,
        )
        for row in ordered:
            counters[row["group"]] = counters.get(row["group"], 0) + 1
            row[f"{lg.key}_rank"] = f"{row['group']}{counters[row['group']]}"

    return out[:top]


def build_html(index: dict | None, stats_state: dict | None, now: datetime) -> str:
    stamp = now.astimezone(CENTRAL).strftime("%a %b %d, %I:%M %p Central")
    head = (
        "<!doctype html><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Fantasy Sports Bible — IDP draft board</title>"
        f"<style>{_STYLE}</style>"
        "<h1>IDP draft board — NDDPL &amp; RED_EYE</h1>"
    )

    if not has_idp_stats(stats_state):
        return (
            head + "<p class='sub'>The stored season stats predate the IDP fields — "
            "the next hourly sync refetches them; try again shortly. "
            f"Checked {html_mod.escape(stamp)}.</p>"
        )

    board = rows(index, stats_state)
    if not board:
        return (
            head + "<p class='sub'>Player index unavailable — the hourly sync "
            f"refreshes it; try again shortly. Checked {html_mod.escape(stamp)}.</p>"
        )

    body_rows = []
    for i, r in enumerate(board, 1):
        nddpl = (
            f"{r['nddpl']:.1f} <span class='grp'>{html_mod.escape(r.get('nddpl_rank', ''))}</span>"
            if r["nddpl"] is not None
            else "<span class='na'>— no DL slot</span>"
        )
        body_rows.append(
            f"<tr><td class='n'>{i}</td>"
            f"<td>{html_mod.escape(r['name'])}"
            + (f" <b>{html_mod.escape(r['injury'])}</b>" if r["injury"] else "")
            + "</td>"
            f"<td>{html_mod.escape(r['position'])}</td>"
            f"<td class='grp'>{html_mod.escape(r['group'])}</td>"
            f"<td>{html_mod.escape(r['team'])}</td>"
            f"<td class='n'>{r['gp'] or ''}</td>"
            f"<td class='n'>{r['solo']:.0f}/{r['ast']:.0f}</td>"
            f"<td class='n'>{r['sack']:.0f}</td>"
            f"<td class='n'>{r['int']:.0f}</td>"
            f"<td class='n'>{r['pd']:.0f}</td>"
            f"<td class='n'>{nddpl}</td>"
            f"<td class='n'>{r['red_eye']:.1f} "
            f"<span class='grp'>{html_mod.escape(r.get('red_eye_rank', ''))}</span></td></tr>"
        )

    return (
        head + f"<p class='sub'>Top {len(board)} defenders by '25 season totals, scored "
        "with each league's own verified settings (docs/LEAGUES.md): NDDPL pays "
        "3/sack &amp; 2/INT and starts 4 DB + 4 LB (no DL slot); RED_EYE pays "
        "2/sack &amp; 3/INT and starts 4 D + 4 DB. Last season's finals wearing "
        "that label — a draft-prep ranking, not a projection · generated "
        f"{html_mod.escape(stamp)} · stats &amp; injury flags: Sleeper</p>"
        "<p class='sub'><b>Owner's read (Aug 20):</b> RED_EYE's D slots go to "
        "LBs in practice and DBs fill the DB slots — so both leagues draft to "
        "the same shape, 4 LB + 4 DB. Tackles rule this scoring, which makes "
        "every-down MIKE linebackers the premium picks; the '25 point totals "
        "below agree, since solo+assist volume dominates them.</p>"
        "<table><thead><tr><th>#</th><th>Player</th><th>Pos</th><th>Grp</th>"
        "<th>Team</th><th>GP</th><th>Solo/Ast</th><th>Sk</th><th>Int</th>"
        "<th>PD</th><th>NDDPL '25</th><th>RED_EYE '25</th></tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table>"
        "<p class='sub' style='margin-top:12px'>One interpretation edge, stated "
        "rather than papered over: positions here are <b>Sleeper's</b> "
        "classification, which can disagree with Yahoo's for edge rushers — a "
        "Sleeper DE that Yahoo lists as LB <i>is</i> startable in an LB slot "
        "despite the dash; check the player's page in your league before "
        "passing. Exact per-league eligibility arrives with Yahoo API "
        "access.</p>"
    )
