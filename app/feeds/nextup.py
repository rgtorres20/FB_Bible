"""Next man up — the pickup board.

Owner ask, Aug 21: *"is there a way to search for latest post of sleepers
or backups (need to be picked up after injuries to starters)?"*

This is that page. Every starter currently flagged out, the player
measured to be behind him, how much work is actually coming loose, and
the real latest wire item about the replacement — so the answer to "who
do I grab" arrives with its evidence attached instead of as an assertion.

What is live here, and what is not, stated because this app's whole
posture is that the difference is visible:

  * **Injury flags: live.** Sleeper's player index, refreshed every sync.
  * **The wire post: live and real.** The newest polled item that mentions
    that player, linked, with its own timestamp. Never a summary.
  * **Depth order and workload: measured, from last season.** Labelled
    '25 everywhere it appears. No free source publishes a current depth
    chart, so the honest substitute is who actually got the ball, and the
    page says which it is.
  * **Nothing is projected.** The vacancy is the starter's own '25
    workload, not a guess at what the backup does with it.

The leagues this was built for have no waivers and no FAAB (CLAUDE.md),
so there are no bid columns and no waiver-clear times: adds are free and
first-come, and the only question worth answering is who and how soon.
"""

from __future__ import annotations

import html as html_mod
from datetime import datetime
from zoneinfo import ZoneInfo

from . import depth, skin

CENTRAL = ZoneInfo("America/Chicago")

_STYLE = (
    skin.TOKENS_CSS
    + """
main { max-width: 900px; margin: 0 auto; }
h1 { font-weight: 900; font-size: 26px; letter-spacing: -0.02em;
     margin: 0 0 4px; text-transform: uppercase; }
.sub { font-size: 12px; color: var(--color-neutral-600); margin: 0 0 16px;
       line-height: 1.55; }
.row { border: 2px solid var(--color-text); background: var(--color-bg);
       box-shadow: 3px 3px 0 var(--color-text); padding: 12px 14px;
       margin-bottom: 14px; }
.head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px;
        margin-bottom: 6px; }
.grab { font-weight: 900; font-size: 19px; letter-spacing: -0.01em; }
.pos { font-size: 11px; font-weight: 800; letter-spacing: 0.1em;
       text-transform: uppercase; color: var(--color-neutral-600); }
.tag { font-size: 9.5px; font-weight: 800; letter-spacing: 0.1em;
       text-transform: uppercase; padding: 2px 6px; border: 1px solid currentColor; }
.tag.out { color: var(--color-accent); }
.because { font-size: 13px; margin: 0 0 8px; }
.because b { font-weight: 800; }
.nums { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 11.5px;
        color: var(--color-neutral-700); margin-bottom: 8px; }
.nums b { color: var(--color-text); font-variant-numeric: tabular-nums; }
.wire { border-left: 3px solid var(--color-neutral-400);
        padding: 4px 0 4px 10px; font-size: 12.5px; }
.wire a { color: inherit; }
.wire .when { color: var(--color-neutral-600); font-size: 11px; }
.quiet { color: var(--color-neutral-600); font-style: italic; }
.depth { font-size: 11px; color: var(--color-neutral-600); margin-top: 6px; }
a { color: inherit; }
"""
)


def _when(stamp: str | None) -> str:
    if not stamp:
        return ""
    try:
        return datetime.fromisoformat(stamp).astimezone(CENTRAL).strftime("%a %b %d, %-I:%M %p")
    except (ValueError, TypeError):
        return ""


def _nums(label: str, player_usage: dict) -> str:
    """A player's measured '25 line, or an honest blank."""
    if not player_usage:
        return f"<span class='quiet'>{label}: no '25 usage — rookie or new role</span>"
    bits = []
    if player_usage.get("gp") is not None:
        bits.append(f"<b>{player_usage['gp']:.0f}</b> games")
    if player_usage.get("rush_att"):
        bits.append(f"<b>{player_usage['rush_att']:.0f}</b> carries")
    if player_usage.get("rec_tgt"):
        bits.append(f"<b>{player_usage['rec_tgt']:.0f}</b> targets")
    if player_usage.get("rz_att"):
        bits.append(f"<b>{player_usage['rz_att']:.0f}</b> RZ carries")
    if player_usage.get("snap_share") is not None:
        bits.append(f"<b>{player_usage['snap_share']}%</b> of snaps")
    if player_usage.get("rush_share") is not None:
        bits.append(f"<b>{player_usage['rush_share']}%</b> of his work on the ground")
    return f"{label}: " + " · ".join(bits) if bits else f"<span class='quiet'>{label}: —</span>"


def build_html(
    index: dict | None,
    stats_state: dict | None,
    items: list[dict] | None,
    now: datetime,
) -> str:
    stamp = now.astimezone(CENTRAL).strftime("%a %b %d, %I:%M %p Central")
    head = skin.head("next man up", "Next man up", _STYLE) + "<main><h1>Next man up</h1>"

    rows = depth.next_man_up(index, stats_state)
    if not rows:
        return (
            head + "<p class='sub'>No starter is currently flagged out — which is "
            "the answer, not an empty page. Injury flags come from the player "
            "index on every sync, so this fills in the moment one lands. "
            f"Checked {html_mod.escape(stamp)}.</p></main>"
        )

    mentions = depth.latest_mentions(items, {r["replacement"]["id"] for r in rows})

    cards = []
    for r in rows:
        starter, backup = r["starter"], r["replacement"]
        item = mentions.get(backup["id"])
        rank = backup["rank"]
        rostered = (
            f"<span class='pos'>Sleeper rank {rank}</span>"
            if rank is not None
            else "<span class='pos'>unranked — likely free</span>"
        )
        wire = (
            "<div class='wire'>"
            + (
                (
                    f"<a href='{html_mod.escape(item.get('link') or '#', quote=True)}'>"
                    f"{html_mod.escape(item.get('title') or '')}</a> "
                    f"<span class='when'>{html_mod.escape(item.get('source') or '')}"
                    + (f" · {_when(item.get('published'))}" if item.get("published") else "")
                    + "</span>"
                )
                if item
                else "<span class='quiet'>No wire mention yet — the polled feeds "
                "have not written about him since this flag landed.</span>"
            )
            + "</div>"
        )
        cards.append(
            "<div class='row'><div class='head'>"
            f"<span class='grab'>{html_mod.escape(backup['name'])}</span>"
            f"<span class='pos'>{html_mod.escape(r['position'])} · "
            f"{html_mod.escape(r['team'])}</span>{rostered}"
            + (
                f"<span class='tag out'>{html_mod.escape(backup['injury'])}</span>"
                if backup["injury"]
                else ""
            )
            + "</div>"
            f"<p class='because'>Behind <b>{html_mod.escape(starter['name'])}</b>, "
            f"who is <b>{html_mod.escape(starter['injury'] or 'out')}</b>.</p>"
            f"<div class='nums'><span>{_nums('Him', backup['usage'])}</span></div>"
            f"<div class='nums'><span>{_nums('The vacancy', starter['usage'])}</span></div>"
            + wire
            + "<div class='depth'>'25 order at "
            + html_mod.escape(f"{r['team']} {r['position']}")
            + ": "
            + html_mod.escape(" › ".join(r["depth"]))
            + "</div></div>"
        )

    return (
        head + f"<p class='sub'><b>{len(rows)}</b> starters are flagged out right now, "
        "and this is who is behind each of them. <b>The flags and the wire posts are "
        "live</b> — Sleeper's index on every sync, and the real newest polled item "
        "about the replacement, linked. <b>The depth order and the workload numbers "
        "are measured from last season</b> and labelled '25: no free source publishes "
        "a current depth chart, so who actually got the ball is the honest substitute. "
        "Nothing here is projected — “the vacancy” is the starter's own '25 workload, "
        "not a guess at what his backup does with it. Your leagues have no waivers and "
        "no bids, so the only question is who and how soon · sorted by how much work "
        f"is coming loose · checked {html_mod.escape(stamp)} · "
        "data: Sleeper, plus the polled wire</p>" + "".join(cards) + "</main>"
    )
