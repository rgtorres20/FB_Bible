"""The scorecard page: what the app predicted, and how it did.

The number this page exists for is not the hit rate — it is the
**calibration** table. A row carries a confidence, so the useful question
is whether 70% means 70%. A model right 60% of the time that says 60% is
more useful than one right 65% of the time that always claims 85%, and
only the calibration column can tell those apart.

Two refusals, both load-bearing:

  * **No rate over an empty set.** Until real games are played there is
    nothing to report, and the page says which games it is waiting for
    rather than showing 0% or a placeholder.
  * **Only falsifiable calls are counted.** TD-lean props are graded
    because a box score settles them. Capsules, wire verdicts, mover
    reads and matchup previews are prose; scoring prose would need an
    invented rubric and would produce a number that looks measured and is
    not. The page states that they are unscored instead of implying full
    coverage.
"""

from __future__ import annotations

import html as html_mod
from datetime import datetime
from zoneinfo import ZoneInfo

from . import scorecard, skin

CENTRAL = ZoneInfo("America/Chicago")

_STYLE = (
    skin.TOKENS_CSS
    + """
main { max-width: 860px; margin: 0 auto; }
h1 { font-weight: 900; font-size: 26px; letter-spacing: -0.02em;
     margin: 0 0 4px; text-transform: uppercase; }
h2 { font-weight: 800; font-size: 12px; letter-spacing: 0.14em;
     text-transform: uppercase; color: var(--color-neutral-600);
     margin: 22px 0 8px; }
.sub { font-size: 12px; color: var(--color-neutral-600); margin: 0 0 16px;
       line-height: 1.55; }
.big { display: flex; flex-wrap: wrap; gap: 22px; border: 2px solid var(--color-text);
       box-shadow: 3px 3px 0 var(--color-text); padding: 14px 16px; margin-bottom: 4px; }
.big div { min-width: 96px; }
.big .n { font-weight: 900; font-size: 30px; letter-spacing: -0.02em;
          font-variant-numeric: tabular-nums; }
.big .k { font-size: 10.5px; font-weight: 800; letter-spacing: 0.1em;
          text-transform: uppercase; color: var(--color-neutral-600); }
table { border-collapse: collapse; width: 100%; font-size: 12.5px; }
th { text-align: left; border-bottom: 2px solid var(--color-text); padding: 4px 6px;
     font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase;
     color: var(--color-neutral-600); }
td { padding: 4px 6px; border-bottom: 1px solid var(--color-neutral-300); }
td.n { text-align: right; font-variant-numeric: tabular-nums; }
.hit { color: var(--color-accent-700); font-weight: 800; }
.miss { color: var(--color-neutral-600); }
.quiet { color: var(--color-neutral-600); font-style: italic; }
.note { border-left: 4px solid var(--color-accent); padding: 8px 12px;
        background: var(--color-neutral-200); font-size: 12.5px; margin: 0 0 16px; }
a { color: inherit; }
"""
)


def _pct(value: int | None) -> str:
    return "—" if value is None else f"{value}%"


def build_html(
    ledger: dict | None,
    scores_state: dict | None,
    now: datetime,
) -> str:
    stamp = now.astimezone(CENTRAL).strftime("%a %b %d, %I:%M %p Central")
    week, reason = scorecard.current_week(scores_state)
    stats = scorecard.summary(ledger)

    head = (
        "<!doctype html><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Fantasy Sports Bible — scorecard</title>"
        f"{skin.FAVICON}<style>{_STYLE}</style>{skin.THEME_BOOT}"
        f"<main>{skin.home_bar('Scorecard')}<h1>Scorecard</h1>"
    )

    intro = (
        "<p class='sub'>Every TD lean this app has published, recorded when "
        "it was made and graded against the real box score. <b>The record is "
        "written before the games and never edited after</b> — a prediction "
        "you can revise once you know the answer is not a prediction. Only "
        "falsifiable calls are counted: a prop with a line is something a box "
        "score settles, while the AI capsules, wire verdicts, mover reads and "
        "matchup previews are prose and stay <b>unscored</b> rather than "
        "graded against an invented rubric."
        f" · checked {html_mod.escape(stamp)}</p>"
    )

    if not stats["settled"]:
        # Two different empty states, and they mean different things: no
        # calls on the record at all, versus calls recorded and waiting
        # for the games that settle them. Neither shows a rate.
        if stats["recorded"]:
            waiting = (
                "<div class='note'><b>Nothing graded yet.</b> "
                f"{html_mod.escape(reason)}. <b>{stats['recorded']}</b> "
                + ("call is" if stats["recorded"] == 1 else "calls are")
                + " on the record and waiting for a result. There is "
                "deliberately no accuracy figure here until there are games "
                "behind it.</div>"
            )
        else:
            waiting = (
                "<div class='note'><b>Nothing recorded yet.</b> "
                f"{html_mod.escape(reason)}. Calls start going on the record "
                "on the next sync once the regular season begins.</div>"
            )
        return head + intro + waiting + "</main>"

    bands = "".join(
        f"<tr><td>{html_mod.escape(b['label'])}</td>"
        f"<td class='n'>{b['n']}</td>"
        f"<td class='n'>{_pct(b['claimed'])}</td>"
        f"<td class='n'><b>{_pct(b['actual'])}</b></td>"
        + (
            f"<td class='n'>{b['actual'] - b['claimed']:+d}</td>"
            if b["claimed"] is not None and b["actual"] is not None
            else "<td class='n'>—</td>"
        )
        + "</tr>"
        for b in stats["bands"]
        if b["n"]
    )

    props = "".join(
        f"<tr><td>{html_mod.escape(prop)}</td><td class='n'>{row['n']}</td>"
        f"<td class='n'>{row['hits']}</td>"
        f"<td class='n'><b>{round(100 * row['hits'] / row['n'])}%</b></td></tr>"
        for prop, row in sorted(stats["by_prop"].items())
    )

    return (
        head + intro + "<div class='big'>"
        f"<div><div class='n'>{stats['rate']}%</div><div class='k'>hit rate</div></div>"
        f"<div><div class='n'>{stats['hits']}–{stats['settled'] - stats['hits']}</div>"
        "<div class='k'>record</div></div>"
        f"<div><div class='n'>{stats['open']}</div><div class='k'>awaiting result</div></div>"
        f"<div><div class='n'>{stats['pushed']}</div><div class='k'>pushed</div></div>"
        "</div>"
        "<p class='sub'>Pushes are excluded from the rate rather than counted "
        "as wins, and calls still awaiting a result are excluded too — a rate "
        "that quietly folded in unplayed games would be the exact thing this "
        "page exists to catch.</p>"
        "<h2>Calibration — does the confidence mean anything?</h2>"
        "<p class='sub'>The column that matters. If “said” and “hit” track each "
        "other, the confidence numbers are informative; if “said” always runs "
        "above “hit”, the app is overconfident and the number is decoration.</p>"
        "<table><thead><tr><th>Confidence band</th><th>Calls</th>"
        "<th>Said</th><th>Hit</th><th>Gap</th></tr></thead>"
        f"<tbody>{bands}</tbody></table>"
        "<h2>By prop</h2>"
        "<table><thead><tr><th>Prop</th><th>Calls</th><th>Hits</th>"
        "<th>Rate</th></tr></thead>"
        f"<tbody>{props}</tbody></table>"
        "</main>"
    )
