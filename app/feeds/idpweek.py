"""/app/idpweek -- the IDP tracker: this week's projected tacklers.

Owner ask, Sep 3: "another tab for idp trackers on defense where it tells
me the highest player with points from that week based on my scoring but
usually I just want to know tackles that means points in idp -- MIKE lbs
are great for this."

Two orderings, both on the page and both honest:

- **tackles first.** Every group's table is ordered by projected tackles
  (solo + assisted), because that is the volume that decides an IDP week
  and it is what the owner said they read. Solo is shown beside the
  total; a MIKE's slot is named so the middle linebackers are visible
  without a filter.
- **points per league beside it.** Each league that starts individual
  defenders gets a column scored under its own IDP values
  (`League.score_idp`) -- so a sack-heavy league and a tackle-heavy
  league disagree in the open. A league that cannot start the group
  shows a dash naming the missing slot, never a zero.

The numbers are Rotowire's weekly projection via Sleeper
(`projections.reduce_week`, LB/DB/DL since Sep 5), joined by Sleeper id
through `gamestack.weekly_stars`. Flags and practice status are Sleeper's
current ones; the wire column is the newest polled item tagging the man.
Nothing here is a season total dressed as a week, and an absent forecast
is an empty page that says so.
"""

from __future__ import annotations

import html as html_mod
from collections.abc import Sequence
from datetime import datetime

from .. import leagues as leagues_mod
from . import skin
from .clock import CENTRAL

GROUPS = ("LB", "DB", "DL")

_STYLE = """
body { font-family: Georgia, 'Times New Roman', serif; margin: 24px;
       color: #16234A; background: #F5F1E6; }
h1 { font-size: 22px; margin: 0 0 2px; }
h2 { font-size: 15px; margin: 22px 0 6px; letter-spacing: 0.04em; text-transform: uppercase; }
.sub { font-size: 12px; color: #5a5a4f; margin-bottom: 14px; max-width: 720px; }
table { border-collapse: collapse; width: 100%; font-size: 11.5px; }
th { text-align: left; border-bottom: 2px solid #16234A; padding: 3px 6px;
     font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase; }
td { padding: 3px 6px; border-bottom: 1px solid #ddd6c4; vertical-align: top; }
td.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.slot { font-weight: bold; }
.na { color: #8a8a7c; }
.flag { color: #8a1c1c; font-weight: bold; font-size: 10.5px; }
.wire { font-size: 10.5px; color: #5a5a4f; }
.wire a { color: #16234A; }
@media print { body { background: #fff; margin: 8mm; } }
"""


def _tackles_first(row: dict, default: str) -> tuple[float, float]:
    pts = row["points"].get(default)
    return (-(row["tackles"] or 0.0), -(pts if pts is not None else -1.0))


def build_html(
    stars: dict | None,
    now: datetime,
    board_leagues: Sequence[leagues_mod.League] | None = None,
) -> str:
    leagues = [lg for lg in (board_leagues or leagues_mod.defaults()) if lg.starts_idp]
    stamp = now.astimezone(CENTRAL).strftime("%a %b %d, %I:%M %p Central")
    head = skin.head("IDP tracker", "IDP tracker", _STYLE)
    if not leagues:
        return head + (
            "<h1>IDP tracker</h1><p class='sub'>None of your leagues starts individual "
            "defenders, so there is nothing to rank here. Team defenses are on the "
            "<a href='/app/idp'>defense board</a>.</p>"
        )
    names = " &amp; ".join(html_mod.escape(lg.name) for lg in leagues)
    head += f"<h1>IDP tracker — {names}</h1>"
    groups = (stars or {}).get("groups") or {}
    if not stars or not any(groups.get(g) for g in GROUPS):
        return head + (
            "<p class='sub'>No weekly forecast for defenders is stored yet — the sync pulls "
            "Rotowire's weekly lines (via Sleeper) for LB, DB and DL once a day; try again "
            f"after the next one. Checked {html_mod.escape(stamp)}.</p>"
        )
    week = stars.get("week")
    source = html_mod.escape(stars.get("source") or "")
    as_of = html_mod.escape(stars.get("as_of") or "")
    out = [
        head,
        f"<p class='sub'>Week {week} projections, {source}"
        + (f", revised {as_of}" if as_of else "")
        + ". Ordered by projected tackles (solo + assisted) because tackles are the IDP "
        "week; points beside them under each league's own IDP values. A dash means that "
        "league cannot start the group. Flags and practice status are Sleeper's current "
        f"ones. Built {html_mod.escape(stamp)}.</p>",
    ]
    default = stars.get("default_league") or leagues[0].key
    for group in GROUPS:
        rows = sorted(groups.get(group) or [], key=lambda r: _tackles_first(r, default))
        if not rows:
            continue
        out.append(f"<h2>{group} — {len(rows)} projected</h2>")
        cols = "".join(f"<th class='n'>{html_mod.escape(lg.name)}</th>" for lg in leagues)
        out.append(
            "<table><thead><tr><th>#</th><th>Player</th><th class='n'>Proj tkl</th>"
            f"<th class='n'>Solo</th>{cols}<th>Wire</th></tr></thead><tbody>"
        )
        for i, r in enumerate(rows, 1):
            flags = []
            if r.get("injury"):
                flags.append(html_mod.escape(r["injury"]))
            if r.get("practice"):
                flags.append("practice: " + html_mod.escape(r["practice"]))
            flag_html = f" <span class='flag'>{' · '.join(flags)}</span>" if flags else ""
            cells = []
            for lg in leagues:
                pts = r["points"].get(lg.key)
                if pts is None:
                    cells.append(f"<td class='n'><span class='na'>— no {group} slot</span></td>")
                else:
                    cells.append(f"<td class='n'>{pts:.1f}</td>")
            wire = r.get("wire")
            wire_html = (
                f"<span class='wire'>{html_mod.escape(wire['time'])} · "
                f"<a href='{html_mod.escape(wire['link'])}' target='_blank' rel='noopener'>"
                f"{html_mod.escape(wire['head'])}</a></span>"
                if wire
                else "<span class='na'>—</span>"
            )
            out.append(
                f"<tr><td class='n'>{i}</td>"
                f"<td>{html_mod.escape(r['name'])} "
                f"<span class='slot'>{html_mod.escape(r['slot'])}</span>"
                f" · {html_mod.escape(r['team'])}{flag_html}</td>"
                f"<td class='n'>{(r['tackles'] or 0):.1f}</td>"
                f"<td class='n'>{(r['solo'] or 0):.1f}</td>"
                + "".join(cells)
                + f"<td>{wire_html}</td></tr>"
            )
        out.append("</tbody></table>")
    return "".join(out)
