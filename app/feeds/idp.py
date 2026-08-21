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
from . import skin

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


def has_dst_stats(stats_state: dict | None) -> bool:
    """Whether the stored stats carry usable team-defense season lines.

    Not "is the field there" -- whether every defense's points-allowed
    ladder accounts for all of its games, which is the reducer's own
    check that those buckets are game counts rather than something else
    numeric. A partial ladder would silently underscore whichever
    defense is missing a band, and an underscored defense reads as a
    ranking rather than as a gap.
    """
    coverage = (stats_state or {}).get("coverage") or {}
    total = coverage.get("defenses") or 0
    return bool(total) and coverage.get("defense_pa_complete") == total


def dst_rows(
    index: dict | None,
    stats_state: dict | None,
    board_leagues: Sequence[leagues_mod.League] | None = None,
) -> list[dict]:
    """Team defenses, scored per league, best first.

    Same contract as `rows`: one score-and-rank pair per league, named
    after the league, and a league that starts no DEF slot contributes
    neither. Ordered by the best score across the leagues that do.
    """
    board = [
        lg
        for lg in (board_leagues if board_leagues is not None else BOARD_LEAGUES)
        if lg.starts_dst
    ]
    if not board:
        return []

    defenses = ((stats_state or {}).get("defenses") or {}) if stats_state else {}
    named = {
        p.get("team") or pid: p
        for pid, p in ((index or {}).get("players") or {}).items()
        if p.get("dst")
    }

    out = []
    for code, entry in defenses.items():
        player = named.get(code) or {}
        row = {
            "id": player.get("id") or code,
            "name": player.get("name") or code,
            "team": code,
            "gp": entry.get("gp"),
            "pts_allow": entry.get("pts_allow"),
            "yds_allow": entry.get("yds_allow"),
            "sack": entry.get("sack", 0),
            "int": entry.get("int", 0),
            "fum_rec": entry.get("fum_rec", 0),
            "td": entry.get("def_st_td", 0),
            # Games held under a touchdown -- the band that decides most
            # streaming calls, and a number the ladder already carries.
            "shutdown": entry.get("pts_allow_0", 0) + entry.get("pts_allow_1_6", 0),
        }
        for lg in board:
            row[lg.key] = lg.score_dst(entry)
        out.append(row)

    out.sort(key=lambda r: max(r[lg.key] for lg in board), reverse=True)
    for lg in board:
        for i, row in enumerate(sorted(out, key=lambda r, k=lg.key: r[k], reverse=True), 1):
            row[f"{lg.key}_rank"] = f"DEF{i}"
    return out


def _scoring_note(lg: leagues_mod.League) -> str:
    """One league's IDP terms in its own numbers, for the caption."""
    values = lg.idp
    bits = []
    for stat_field, label in (("idp_sack", "sack"), ("idp_int", "INT")):
        if values.get(stat_field):
            bits.append(f"{values[stat_field]:g}/{label}")
    groups = "/".join(sorted(lg.idp_groups)) or "no defenders"
    starts = sum(1 for s in lg.slots if s in {"DB", "LB", "DL", "D"})
    return (
        f"<b>{html_mod.escape(lg.name)}</b> pays "
        + (" &amp; ".join(bits) or "no sack or INT points")
        + f" and starts {starts} ({groups})"
    )


def _dst_note(lg: leagues_mod.League) -> str:
    """One league's D/ST terms in its own numbers."""
    bits = []
    for stat_field, label in (("sack", "sack"), ("int", "INT"), ("def_st_td", "TD")):
        if lg.dst.get(stat_field):
            bits.append(f"{lg.dst[stat_field]:g}/{label}")
    shutout = lg.dst_pa.get("pts_allow_0")
    if shutout:
        bits.append(f"{shutout:g} for a shutout")
    terms = " &amp; ".join(bits) or "no per-event points"
    return f"<b>{html_mod.escape(lg.name)}</b> pays {terms}"


def build_html(
    index: dict | None,
    stats_state: dict | None,
    now: datetime,
    board_leagues: Sequence[leagues_mod.League] | None = None,
) -> str:
    """The board, with one score column per league.

    `board_leagues` is how a signed-in user's own leagues (/app/leagues)
    get scored here: same dataclass, same code path, so their 4-a-sack
    league ranks defenders its own way rather than the owner's.
    """
    board_ls = list(board_leagues if board_leagues is not None else BOARD_LEAGUES)
    # A league belongs on this page if it starts defense of either kind.
    # Filtering on IDP alone would drop a league whose only defensive
    # slot is a team D/ST -- and silently fall back to the owner's two,
    # which is somebody else's board wearing this user's sign-in.
    board_ls = [lg for lg in board_ls if lg.starts_idp or lg.starts_dst] or list(BOARD_LEAGUES)
    idp_ls = [lg for lg in board_ls if lg.starts_idp]
    stamp = now.astimezone(CENTRAL).strftime("%a %b %d, %I:%M %p Central")
    title = " &amp; ".join(html_mod.escape(lg.name) for lg in board_ls)
    # A league that starts only a team D/ST has no IDP board to speak of,
    # and calling its page one would be a small lie in large type.
    kind = "IDP draft board" if idp_ls else "Defense draft board"
    head = (
        "<!doctype html><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>Fantasy Sports Bible — {kind}</title>"
        f"{skin.FAVICON}"
        f"<style>{_STYLE}</style>"
        f"<h1>{kind} — {title}</h1>"
    )

    dst_table = _dst_table(index, stats_state, board_ls)

    # No league here starts individual defenders -- a team-D/ST-only
    # league. The page is that league's D/ST board and nothing else,
    # rather than 150 rows it cannot roster.
    if not idp_ls:
        return head + dst_table

    if not has_idp_stats(stats_state):
        return (
            head + dst_table + "<p class='sub'>The stored season stats predate the IDP "
            "fields — the next hourly sync refetches them; try again shortly. "
            f"Checked {html_mod.escape(stamp)}.</p>"
        )

    board = rows(index, stats_state, board_leagues=idp_ls)
    if not board:
        return (
            head + dst_table + "<p class='sub'>Player index unavailable — the hourly "
            f"sync refreshes it; try again shortly. Checked {html_mod.escape(stamp)}.</p>"
        )

    body_rows = []
    for i, r in enumerate(board, 1):
        cells = []
        for lg in idp_ls:
            if r[lg.key] is None:
                # Arithmetically scoreable, practically unrosterable. The
                # dash says which, and why.
                cells.append(f"<td class='n'><span class='na'>— no {r['group']} slot</span></td>")
            else:
                rank = html_mod.escape(r.get(f"{lg.key}_rank", ""))
                cells.append(f"<td class='n'>{r[lg.key]:.1f} <span class='grp'>{rank}</span></td>")
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
            f"<td class='n'>{r['pd']:.0f}</td>" + "".join(cells) + "</tr>"
        )

    heads = "".join(f"<th>{html_mod.escape(lg.name)} '25</th>" for lg in idp_ls)
    owner_read = (
        "<p class='sub'><b>Owner's read (Aug 20):</b> RED_EYE's D slots go to "
        "LBs in practice and DBs fill the DB slots — so both leagues draft to "
        "the same shape, 4 LB + 4 DB. Tackles rule this scoring, which makes "
        "every-down MIKE linebackers the premium picks; the '25 point totals "
        "below agree, since solo+assist volume dominates them.</p>"
        # Only when the IDP columns are exactly the owner's own two --
        # this read is about how THOSE rooms play their slots, and it
        # would be a claim about somebody else's league otherwise.
        # Compared against the IDP-starting built-ins, not all of them:
        # BALLAPALOSA is a built-in that starts no defenders at all.
        if [lg.key for lg in idp_ls] == [lg.key for lg in BOARD_LEAGUES if lg.starts_idp]
        else ""
    )

    return (
        head
        + dst_table
        + f"<p class='sub'>Top {len(board)} defenders by '25 season totals, scored "
        "with each league's own settings: "
        + "; ".join(_scoring_note(lg) for lg in idp_ls)
        + ". Last season's finals wearing that label — a draft-prep ranking, "
        "not a projection · generated "
        f"{html_mod.escape(stamp)} · stats &amp; injury flags: Sleeper</p>"
        + owner_read
        + "<table><thead><tr><th>#</th><th>Player</th><th>Pos</th><th>Grp</th>"
        "<th>Team</th><th>GP</th><th>Solo/Ast</th><th>Sk</th><th>Int</th>"
        f"<th>PD</th>{heads}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table>"
        "<p class='sub' style='margin-top:12px'>One interpretation edge, stated "
        "rather than papered over: positions here are <b>Sleeper's</b> "
        "classification, which can disagree with Yahoo's for edge rushers — a "
        "Sleeper DE that Yahoo lists as LB <i>is</i> startable in an LB slot "
        "despite the dash; check the player's page in your league before "
        "passing. Exact per-league eligibility arrives with Yahoo API "
        "access.</p>"
    )


def _n(value) -> str:
    """A count for a table cell, or an empty cell when it is not there."""
    return "" if value is None else f"{value:.0f}"


def _dst_table(
    index: dict | None,
    stats_state: dict | None,
    board_ls: Sequence[leagues_mod.League],
) -> str:
    """Team defenses, for the leagues that start one.

    Rendered above the individual defenders because a DEF slot is a
    starting slot like any other, and a league that has one drafts it
    from a pool of 32 rather than 400 -- the scarcer decision belongs
    first. A league with no DEF slot sees nothing here at all.
    """
    with_dst = [lg for lg in board_ls if lg.starts_dst]
    if not with_dst:
        return ""

    heading = (
        "<h2 style='font-size:16px;margin:18px 0 2px'>Team defenses — "
        + " &amp; ".join(html_mod.escape(lg.name) for lg in with_dst)
        + "</h2>"
    )
    if not has_dst_stats(stats_state):
        return (
            heading + "<p class='sub'>The stored season stats don't carry complete "
            "team-defense lines yet — the weekly stats refetch fills them in. "
            "Shown empty rather than ranked from a partial ladder.</p>"
        )

    board = dst_rows(index, stats_state, board_leagues=with_dst)
    if not board:
        return heading + "<p class='sub'>No team-defense lines in the stored stats yet.</p>"

    body = []
    for i, r in enumerate(board, 1):
        cells = "".join(
            f"<td class='n'>{r[lg.key]:.1f} "
            f"<span class='grp'>{html_mod.escape(r.get(f'{lg.key}_rank', ''))}</span></td>"
            for lg in with_dst
        )
        # Blank cells rather than zeros for anything the stored line does
        # not carry: `f"{None:.0f}"` raises, and one defense short of one
        # field would take the whole page down with it.
        counted = "".join(
            f"<td class='n'>{_n(r[k])}</td>"
            for k in ("gp", "sack", "int", "fum_rec", "td", "shutdown", "pts_allow")
        )
        body.append(
            f"<tr><td class='n'>{i}</td>"
            f"<td>{html_mod.escape(r['name'])}</td>"
            f"<td>{html_mod.escape(r['team'])}</td>" + counted + cells + "</tr>"
        )

    heads = "".join(f"<th>{html_mod.escape(lg.name)} '25</th>" for lg in with_dst)
    return (
        heading + f"<p class='sub'>{len(board)} team defenses by '25 season totals, "
        "scored with your own D/ST settings: " + "; ".join(_dst_note(lg) for lg in with_dst) + ". "
        "“U7” is games held under a touchdown — the band that decides most "
        "streaming calls. Last season's finals wearing that label, not a "
        "projection · one number this cannot carry: kick and punt return "
        "yardage, which most leagues credit to the returner rather than the "
        "defense · stats: Sleeper</p>"
        "<table><thead><tr><th>#</th><th>Defense</th><th>Tm</th><th>GP</th>"
        "<th>Sk</th><th>Int</th><th>FR</th><th>TD</th><th>U7</th><th>PA</th>"
        f"{heads}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )
