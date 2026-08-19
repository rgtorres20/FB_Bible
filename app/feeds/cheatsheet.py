"""Printable draft cheat sheet, generated from the live blended board.

One page the owner can print the morning of each draft: the FFC board for
both league sizes with the blend, Sleeper's rank beside it, round dividers,
and a star on the position-adjusted sleeper finds. Server-rendered plain
HTML on purpose -- it must print cleanly and load with zero scripts.

The league caveat is structural, not stylistic. The owner's verified Yahoo
settings (docs/LEAGUES.md, from the settings pages themselves, Aug 19) say
both leagues score QBs well above the market the ADP reflects -- 6-point
passing TDs and 20 yards/point in both, plus a full point per completion
in RED_EYE -- and both start 8 IDP players this sheet does not carry. The
sheet says so instead of assuming the reader remembers. (The original
"rushing league, QBs score nothing" note had it exactly backwards; it came
from chat-era memory and died on contact with the real settings page.)
"""

from __future__ import annotations

import html
from datetime import datetime
from zoneinfo import ZoneInfo

from . import adp as adp_mod

CENTRAL = ZoneInfo("America/Chicago")

_STYLE = """
body { font-family: Georgia, 'Times New Roman', serif; margin: 24px;
       color: #16234A; background: #F5F1E6; }
h1 { font-size: 22px; margin: 0 0 2px; }
.sub { font-size: 12px; color: #5a5a4f; margin-bottom: 14px; }
.note { font-size: 12px; background: #fff; border-left: 3px solid #E3311D;
        padding: 8px 10px; margin: 0 0 14px; max-width: 640px; }
table { border-collapse: collapse; width: 100%; font-size: 11px; }
th { text-align: left; border-bottom: 2px solid #16234A; padding: 3px 6px;
     font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase; }
td { padding: 2px 6px; border-bottom: 1px solid #ddd6c4; }
tr.round td { border-top: 2px solid #16234A; }
td.n { text-align: right; font-variant-numeric: tabular-nums; }
.star { color: #E3311D; font-weight: bold; }
@media print {
  body { background: #fff; margin: 8mm; }
  .note { border-left-color: #000; }
}
"""


def build_html(state: dict, index: dict | None, now: datetime) -> str:
    board = (state or {}).get("players") or []
    stamp = now.astimezone(CENTRAL).strftime("%a %b %d, %I:%M %p Central")

    if not board:
        return (
            "<!doctype html><meta charset='utf-8'><title>FB Bible cheat sheet</title>"
            f"<style>{_STYLE}</style><h1>Draft cheat sheet</h1>"
            "<p class='sub'>No live ADP board yet — the hourly sync fills this in. "
            f"Checked {html.escape(stamp)}.</p>"
        )

    finds = {
        entry["name"]
        for entry in adp_mod.build_scout(state, index=index)
        if entry["kind"] == "Sleeper find"
    }
    ranks = adp_mod._rank_lookup(index)

    rows = []
    last_round = 0
    for i, entry in enumerate(board, start=1):
        blend = entry["adp"]
        round_12 = int((blend - 1) // 12) + 1
        cls = ' class="round"' if round_12 != last_round else ""
        last_round = round_12

        key = " ".join(adp_mod.players_mod.normalize(entry["name"]).split())
        rank = ranks.get(key)
        star = ' <span class="star">★</span>' if entry["name"] in finds else ""
        sizes = entry.get("sizes", {})
        rows.append(
            f"<tr{cls}><td class='n'>{i}</td>"
            f"<td>{html.escape(entry['name'])}{star}</td>"
            f"<td>{html.escape(entry.get('position') or '')}</td>"
            f"<td>{html.escape(entry.get('team') or 'FA')}</td>"
            f"<td class='n'>{entry.get('bye') or ''}</td>"
            f"<td class='n'>{sizes.get('12', '')}</td>"
            f"<td class='n'>{sizes.get('10', '')}</td>"
            f"<td class='n'><b>{blend}</b></td>"
            f"<td class='n'>{rank if rank is not None else ''}</td></tr>"
        )

    return (
        "<!doctype html><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>FB Bible cheat sheet</title>"
        f"<style>{_STYLE}</style>"
        "<h1>Draft cheat sheet — NDDPL &amp; RED_EYE (both 10tm)</h1>"
        f"<p class='sub'>Live ADP from real PPR mock drafts, blended across both "
        f"league sizes · ★ = position-adjusted sleeper find · generated {html.escape(stamp)} · "
        "data: FantasyFootballCalculator + Sleeper</p>"
        "<p class='note'><b>Both leagues score QBs above this market</b> (verified "
        "Yahoo settings, Aug 19): 6-pt passing TDs and 20 pass yds/pt in both, plus "
        "1 pt per completion in RED_EYE — so market ADP underprices QBs here; take "
        "them earlier than listed. Receiving yards are halved (20 yds/pt) in both, "
        "favoring high-catch receivers. Each league also starts 8 IDP players this "
        "sheet does not carry.</p>"
        "<table><thead><tr><th>#</th><th>Player</th><th>Pos</th><th>Team</th>"
        "<th>Bye</th><th>12tm</th><th>10tm</th><th>Blend</th><th>Slpr</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
