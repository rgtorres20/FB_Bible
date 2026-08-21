"""Who actually scores the most, in each league's own currency.

Owner ask, Aug 21: *"we need to make a page for in season. We want to see
the active list of top players based on their stats in season… I want to
see who would score the most points in each league."*

Every other board in this app ranks by somebody's *opinion* -- ADP, a
cheat sheet, a blend of both. This one ranks by arithmetic: take a
player's real stat line, multiply it by the league's real scoring values,
sort. Nothing here is a projection and nothing here is a market read.

That makes it the surface where a league's quirks stop being prose and
become an ordering. RED_EYE pays a point per completion, so its
quarterbacks land somewhere no consensus board would put them. Both
verified leagues halve receiving yardage while keeping full PPR, so
target volume outranks air yards. NDDPL and RED_EYE start eight
defenders each and BALLAPALOSA starts a team defense instead -- so the
same player is a top-30 asset in one column and a dash in another.

## The three scorings, and which applies

A league scores a player exactly one way, decided by what it can start:

- **Offence** (`score_offense`) for everyone the index does not mark as a
  defender. Every league starts them, so this column is never a dash.
- **Individual defenders** (`score_idp`), and only for the groups the
  league actually starts. A defensive lineman in NDDPL -- which has no DL
  slot -- is a dash, not a number. The score would be arithmetically fine
  and practically a lie.
- **Team defenses** (`score_dst`), only where the league starts a DEF
  slot. A league starts individual defenders or a team defense, never
  both (docs/LEAGUES.md), so no player is scored twice.

## What the numbers are, and are not

- **Season totals, from stored aggregates.** The headline is the total,
  because a total is what wins a league. Per-game sits beside it, because
  a total is also what makes a player who missed ten games look finished.
  Neither is derived from the other by guesswork -- games played is a
  stored field.
- **Raw points, not points above replacement.** PAR is the more useful
  number and the easier one to get quietly wrong: it needs a defensible
  replacement baseline per slot per league. Raw first.
- **Not a projection.** The as-of label says which season, and the page
  repeats it rather than letting a big number imply freshness.
- **BALLAPALOSA reads slightly low**, and says so. Its per-game bonuses
  cannot be recovered from season aggregates -- one 175-yard game and two
  90-yard games are identical in a total. `score_offense` carries the
  same caveat; this page surfaces it where someone comparing columns
  would otherwise read the gap as a scoring difference.
"""

from __future__ import annotations

import html as html_mod
from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from .. import leagues as leagues_mod
from . import skin

CENTRAL = ZoneInfo("America/Chicago")

TOP = 200

# Enough of a line to be worth ranking. Below this the per-game figure is
# arithmetic on noise -- one carry in one game extrapolates to a season.
MIN_GAMES = 1

BOARD_LEAGUES = leagues_mod.defaults()

_STYLE = """
body { font-family: Georgia, 'Times New Roman', serif; margin: 24px;
       color: #16234A; background: #F5F1E6; }
h1 { font-size: 22px; margin: 0 0 2px; }
.sub { font-size: 12px; color: #5a5a4f; margin-bottom: 14px; max-width: 760px; }
.note { font-size: 11px; color: #5a5a4f; margin: 10px 0 14px; max-width: 760px;
        border-left: 3px solid #c9bfa4; padding-left: 10px; }
table { border-collapse: collapse; width: 100%; font-size: 11.5px; }
th { text-align: left; border-bottom: 2px solid #16234A; padding: 3px 6px;
     font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase; }
td { padding: 3px 6px; border-bottom: 1px solid #ddd6c4; }
td.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.pg { color: #5a5a4f; font-size: 10.5px; }
.na { color: #8a8a7c; }
.best { font-weight: bold; }
.empty { font-size: 13px; padding: 18px 0; }
@media print { body { background: #fff; margin: 8mm; } }
"""


def has_offense_stats(stats_state: dict | None) -> bool:
    """Whether the stored stats were reduced with the offensive fields.

    `pass_cmp` is the sentinel: it arrived with the Aug 21 batch that made
    offence scoreable at all, so its absence means the stored blob predates
    them. Rendering a table off the older shape would rank every
    quarterback at zero, which reads as a finding rather than a gap.
    """
    coverage = ((stats_state or {}).get("coverage") or {}).get("players") or {}
    return bool(coverage.get("pass_cmp"))


def _per_game(total: float, games: int | None) -> float | None:
    if not games:
        return None
    return round(total / games, 1)


def rows(
    index: dict | None,
    stats_state: dict | None,
    top: int = TOP,
    board_leagues: Sequence[leagues_mod.League] | None = None,
) -> list[dict]:
    """Every scoreable player, totalled per league, best first.

    One score-and-rank pair per league named after the league -- `nddpl`,
    `nddpl_pg`, `nddpl_rank` -- the same contract `idp.rows` uses, so a
    user-defined league lands in the rows without callers learning a new
    shape. `None` means "this league cannot start him", never zero.
    """
    board = list(board_leagues if board_leagues is not None else BOARD_LEAGUES)
    players = (index or {}).get("players") or {}
    stats = ((stats_state or {}).get("players") or {}) if stats_state else {}

    out: list[dict] = []
    for pid, player in players.items():
        entry = stats.get(pid)
        if not entry:
            continue
        games = entry.get("gp") or 0
        if games < MIN_GAMES:
            continue
        group = player.get("idp")
        row = {
            "id": pid,
            "name": player.get("name") or "",
            "position": player.get("position") or "",
            "group": group or "",
            "team": player.get("team") or "FA",
            "injury": (player.get("injury_status") or "").strip(),
            "gp": games,
        }
        for lg in board:
            if group:
                # A defender only scores where the league starts his group.
                total = lg.score_idp(entry) if group in lg.idp_groups else None
            else:
                total = lg.score_offense(entry)
            row[lg.key] = total
            row[f"{lg.key}_pg"] = _per_game(total, games) if total is not None else None
        if all(row[lg.key] is None for lg in board):
            continue
        if all((row[lg.key] or 0) <= 0 for lg in board):
            continue
        out.append(row)

    out.sort(key=lambda r: max((r[lg.key] or 0) for lg in board), reverse=True)

    # Position rank within each league, over the players that league can
    # actually start. Counted before the page cut so rank 200 means the
    # 200th, not the 200th of whatever survived the slice.
    for lg in board:
        counters: dict[str, int] = {}
        ordered = sorted(
            (r for r in out if r[lg.key] is not None),
            key=lambda r, k=lg.key: r[k],
            reverse=True,
        )
        for row in ordered:
            slot = row["group"] or row["position"] or "?"
            counters[slot] = counters.get(slot, 0) + 1
            row[f"{lg.key}_rank"] = f"{slot}{counters[slot]}"

    return out[:top]


def dst_rows(
    index: dict | None,
    stats_state: dict | None,
    board_leagues: Sequence[leagues_mod.League] | None = None,
) -> list[dict]:
    """Team defenses, totalled per league that starts one.

    Kept separate from `rows` rather than merged into it: a team defense
    is not comparable to a player on volume, and interleaving them would
    put a defense between two wide receivers on a list whose whole claim
    is that the ordering means something.
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
        games = entry.get("gp") or 0
        if games < MIN_GAMES:
            continue
        player = named.get(code) or {}
        row = {
            "id": player.get("id") or code,
            "name": player.get("name") or code,
            "team": code,
            "gp": games,
        }
        for lg in board:
            total = lg.score_dst(entry)
            row[lg.key] = total
            row[f"{lg.key}_pg"] = _per_game(total, games)
        out.append(row)

    out.sort(key=lambda r: max(r[lg.key] for lg in board), reverse=True)
    for lg in board:
        for n, row in enumerate(sorted(out, key=lambda r, k=lg.key: r[k], reverse=True), start=1):
            row[f"{lg.key}_rank"] = f"DEF{n}"
    return out


def _scoring_note(league: leagues_mod.League) -> str:
    """The one or two values that make this league score differently.

    Not a full rules dump -- the point is to explain why the column is
    ordered the way it is, and a wall of numbers explains nothing.
    """
    bits = [f"{league.pass_td:.0f}-pt passing TDs", f"{league.pass_yds_per_pt:.0f} pass yds/pt"]
    if league.pass_completion:
        bits.append(f"{league.pass_completion:g} per completion")
    if league.receiving_is_halved:
        bits.append(f"receiving halved at {league.rec_yds_per_pt:.0f} yds/pt")
    if league.ppr:
        bits.append(f"{league.ppr:g} PPR")
    return f"<b>{html_mod.escape(league.name)}</b> — " + ", ".join(bits)


def _cell(total: float | None, per_game: float | None, rank: str, dash: str) -> str:
    if total is None:
        return f"<td class='n'><span class='na'>{dash}</span></td>"
    pg = f" <span class='pg'>{per_game:.1f}/g</span>" if per_game is not None else ""
    return f"<td class='n'>{total:.1f}{pg} <span class='pg'>{html_mod.escape(rank)}</span></td>"


def _dst_table(
    index: dict | None,
    stats_state: dict | None,
    board_ls: Sequence[leagues_mod.League],
) -> str:
    board = [lg for lg in board_ls if lg.starts_dst]
    dst = dst_rows(index, stats_state, board_leagues=board)
    if not dst:
        return ""
    heads = "".join(f"<th>{html_mod.escape(lg.name)}</th>" for lg in board)
    body = []
    for i, r in enumerate(dst, 1):
        cells = "".join(
            _cell(r[lg.key], r[f"{lg.key}_pg"], r.get(f"{lg.key}_rank", ""), "—") for lg in board
        )
        body.append(
            f"<tr><td class='n'>{i}</td><td>{html_mod.escape(r['name'])}</td>"
            f"<td>{html_mod.escape(r['team'])}</td>"
            f"<td class='n'>{r['gp'] or ''}</td>{cells}</tr>"
        )
    return (
        "<h2 style='font-size:15px; margin:20px 0 4px;'>Team defenses</h2>"
        "<p class='sub'>Scored separately because a defense is not comparable "
        "to a player on volume — interleaving them would put a D/ST between two "
        "receivers on a list whose whole claim is that the order means something.</p>"
        "<table><thead><tr><th>#</th><th>Defense</th><th>Team</th><th>GP</th>"
        f"{heads}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


def build_html(
    index: dict | None,
    stats_state: dict | None,
    now: datetime,
    board_leagues: Sequence[leagues_mod.League] | None = None,
) -> str:
    """The scoring board: real stat lines through each league's real values."""
    board_ls = list(board_leagues if board_leagues is not None else BOARD_LEAGUES)
    stamp = now.astimezone(CENTRAL).strftime("%a %b %d, %I:%M %p Central")
    season = (stats_state or {}).get("season")
    label = f"{season} season" if season else "the stored season"
    title = " &amp; ".join(html_mod.escape(lg.name) for lg in board_ls)
    head = skin.head("Scoring board", "Scoring board", _STYLE) + f"<h1>Scoring board — {title}</h1>"

    if not has_offense_stats(stats_state):
        # The older stored shape carries no passing or receiving fields, so
        # every quarterback would total zero. A table of zeroes reads as a
        # finding; this reads as the gap it is.
        return (
            head + "<p class='empty'>The stored season stats predate the scoring "
            "fields — the next hourly sync refetches them; try again shortly. "
            f"Checked {html_mod.escape(stamp)}.</p>"
        )

    board = rows(index, stats_state, board_leagues=board_ls)
    if not board:
        return (
            head + "<p class='empty'>Player index unavailable — the hourly sync "
            f"refreshes it; try again shortly. Checked {html_mod.escape(stamp)}.</p>"
        )

    body_rows = []
    for i, r in enumerate(board, 1):
        cells = "".join(
            _cell(
                r[lg.key],
                r[f"{lg.key}_pg"],
                r.get(f"{lg.key}_rank", ""),
                f"— no {r['group']} slot" if r["group"] else "—",
            )
            for lg in board_ls
        )
        body_rows.append(
            f"<tr><td class='n'>{i}</td>"
            f"<td>{html_mod.escape(r['name'])}"
            + (f" <b>{html_mod.escape(r['injury'])}</b>" if r["injury"] else "")
            + "</td>"
            f"<td>{html_mod.escape(r['position'])}</td>"
            f"<td>{html_mod.escape(r['team'])}</td>"
            f"<td class='n'>{r['gp'] or ''}</td>{cells}</tr>"
        )

    heads = "".join(f"<th>{html_mod.escape(lg.name)}</th>" for lg in board_ls)
    # Named only where it applies, so it is a caveat about a column rather
    # than a disclaimer draped over the whole page.
    caveat = "".join(
        "<p class='note'><b>"
        + html_mod.escape(lg.name)
        + " reads as a floor.</b> It pays bonuses on a single game's line — "
        + html_mod.escape("; ".join(lg.per_game_bonuses))
        + " — and a season total cannot tell one 175-yard game from two "
        "90-yard games. Weekly lines would settle it. Naming what is missing "
        "beats a column that is quietly short.</p>"
        for lg in board_ls
        if lg.has_per_game_bonuses
    )

    return (
        head + f"<p class='sub'>Top {len(board)} players by <b>{html_mod.escape(label)} "
        "totals run through each league's own scoring</b> — arithmetic, not a "
        "market read and not a projection. Season total is the headline because "
        "a total is what wins a league; the smaller <span class='pg'>x/g</span> "
        "beside it is per game, because a total is also what makes a player who "
        "missed half the year look finished. "
        + "; ".join(_scoring_note(lg) for lg in board_ls)
        + f". Generated {html_mod.escape(stamp)} · stats &amp; injury flags: Sleeper</p>"
        + caveat
        + f"<table><thead><tr><th>#</th><th>Player</th><th>Pos</th><th>Team</th>"
        f"<th>GP</th>{heads}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table>"
        + _dst_table(index, stats_state, board_ls)
        + "<p class='sub' style='margin-top:12px'>A dash means the league cannot "
        "start that player, not that he scored nothing — a defensive lineman in a "
        "league with no DL slot is unrosterable, and a number there would be "
        "arithmetically fine and practically a lie. Kickers are scored at a flat "
        "value per made field goal: Yahoo's distance tiers are a per-league "
        "setting this repo has not verified, and guessing 3/4/5 by yardage would "
        "be inventing a number.</p>"
    )
