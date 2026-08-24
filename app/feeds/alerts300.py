"""The top-300 alert board: one row per ranked player, wire-checked.

The Alerts tab answers "what happened"; this page answers the draft-prep
inverse: "for each of the 300 players who might matter, what is the latest
word — and is there any?" One server-rendered page (same zero-script rule
as the cheat sheet: it must load fast and print cleanly), 300 rows by
Sleeper's fantasy search rank, each carrying:

  - the player's live Sleeper injury flag, when one is set
  - the blended live ADP, when the FFC board covers them
  - the newest wire item tagging them: time, outlet, headline
  - the drafted line for that item — "AI draft:" when the hourly job has
    one, else the rule-based "Auto:" annotation, both honest about
    authorship — or an explicit "no wire mention" when the archive holds
    nothing, which is information too

Nothing here is a judgement: the owner's calls live on the Alerts tab and
never on this page.

Offense and defense are separate sections (owner request, Aug 20: "I
quickly see Offense updates only, and when I care about defense I'll
look"): the top 300 offensive players first, then the top 100 defenders by
the same Sleeper rank, each section with its own table and a jump link at
the top.
"""

from __future__ import annotations

import html as html_mod
from datetime import datetime
from zoneinfo import ZoneInfo

from . import board, impact, render, skin
from . import players as players_mod

CENTRAL = ZoneInfo("America/Chicago")

TOP = 300
# Defenders get their own section, deep enough for 8 IDP starters x 10
# teams with margin but not so deep it buries the signal.
DEF_TOP = 100

_STYLE = """
body { font-family: Georgia, 'Times New Roman', serif; margin: 24px;
       color: #16234A; background: #F5F1E6; }
h1 { font-size: 22px; margin: 0 0 2px; }
h2 { font-size: 15px; margin: 18px 0 6px; border-bottom: 2px solid #16234A;
     padding-bottom: 3px; }
.sub { font-size: 12px; color: #5a5a4f; margin-bottom: 14px; }
table { border-collapse: collapse; width: 100%; font-size: 11.5px; }
th { text-align: left; border-bottom: 2px solid #16234A; padding: 3px 6px;
     font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase; }
td { padding: 3px 6px; border-bottom: 1px solid #ddd6c4; vertical-align: top; }
td.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.flag { color: #E3311D; font-weight: bold; font-size: 10px;
        text-transform: uppercase; letter-spacing: 0.04em; }
.ai { color: #16234A; font-weight: bold; }
.auto { color: #5a5a4f; }
.quiet { color: #8a8a7c; font-style: italic; }
.wire { color: #5a5a4f; font-size: 10.5px; }
a { color: inherit; }
@media print { body { background: #fff; margin: 8mm; } }
"""


def _ranked_players(index: dict | None) -> list[dict]:
    """Top-300 by Sleeper search rank, offense and defense mixed. Rank ties
    are broken by id for a stable page between renders. (The capsule work
    list reads this; the board itself renders the split below.)"""
    players = (index or {}).get("players") or {}
    ranked = [p for p in players.values() if p.get("rank") is not None]
    ranked.sort(key=lambda p: (p["rank"], p.get("id") or ""))
    return ranked[:TOP]


def _split_sections(index: dict | None) -> tuple[list[dict], list[dict]]:
    """(top-300 offense, top-100 defense), each by Sleeper rank."""
    players = (index or {}).get("players") or {}
    ranked = [p for p in players.values() if p.get("rank") is not None]
    ranked.sort(key=lambda p: (p["rank"], p.get("id") or ""))
    offense = [p for p in ranked if not p.get("idp")][:TOP]
    defense = [p for p in ranked if p.get("idp")][:DEF_TOP]
    return offense, defense


def _latest_mentions(items: list[dict]) -> dict[str, dict]:
    """{player id: newest item tagging them}. A mention is a mention -- this
    reads the full stored wire, not the impact-filtered page cut."""
    latest: dict[str, dict] = {}
    for item in sorted(items, key=lambda i: i.get("published") or "", reverse=True):
        for tagged in item.get("players") or []:
            pid = tagged.get("id")
            if pid and pid not in latest:
                latest[pid] = item
    return latest


def _adp_lookup(adp_state: dict | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for entry in (adp_state or {}).get("players") or []:
        value = entry.get("adp")
        if isinstance(value, int | float):
            out.setdefault(board.match_key(entry.get("name", "")), float(value))
    return out


def _line(item: dict, verdicts: dict[str, str], ranks: dict[str, int]) -> tuple[str, str]:
    """(css class, text) for the item's drafted line, authorship labelled."""
    verdict = verdicts.get(item.get("id", ""))
    if verdict:
        return "ai", f"AI draft: {verdict}"
    auto = impact.annotate(impact.score(item, ranks))
    if auto:
        return "auto", auto
    return "quiet", "—"


def build_html(
    index: dict | None,
    items: list[dict],
    verdicts: dict[str, str],
    adp_state: dict | None,
    now: datetime,
    capsules: dict[str, dict] | None = None,
) -> str:
    stamp = now.astimezone(CENTRAL).strftime("%a %b %d, %I:%M %p Central") + players_mod.age_note(
        index, now
    )
    head = skin.head("top-300 alert board", "Alert board", _STYLE) + "<h1>Top-300 alert board</h1>"

    offense, defense = _split_sections(index)
    if not offense and not defense:
        return (
            head + "<p class='sub'>Player index unavailable — the hourly sync "
            f"refreshes it; try again shortly. Checked {html_mod.escape(stamp)}.</p>"
        )

    ranks = {p["id"]: p["rank"] for p in offense + defense if p.get("id")}
    mentions = _latest_mentions(items)
    adp = _adp_lookup(adp_state)
    capsules = capsules or {}
    totals = {"mentioned": 0, "drafted": 0, "angles": 0}

    def render_rows(players: list[dict]) -> str:
        rows = []
        for player in players:
            pid = player.get("id") or ""
            name = player.get("name") or ""
            flag = (player.get("injury_status") or "").strip()
            blend = adp.get(board.match_key(name))
            item = mentions.get(pid)

            if item is None:
                wire = "<span class='quiet'>No wire mention in the last 21 days</span>"
                line_cls, line = "quiet", ""
            else:
                totals["mentioned"] += 1
                when = render.format_time(item.get("published"))
                source = item.get("source_name") or "wire"
                title = (item.get("title") or "").strip()
                body = html_mod.escape(f"{when} · {source} — {title}")
                link = item.get("link") or ""
                if link:
                    body = f"<a href='{html_mod.escape(link, quote=True)}'>{body}</a>"
                wire = f"<span class='wire'>{body}</span>"

            # A capsule is the per-player synthesis (rank, ADP, '25 usage,
            # the newest wire word in one line) and outranks the per-item
            # line when both exist. It also gives quiet players a grounded
            # line where the column would otherwise sit empty.
            capsule = (capsules.get(pid) or {}).get("text")
            if capsule:
                totals["angles"] += 1
                line_cls, line = "ai", f"AI angle: {capsule}"
            elif item is not None:
                line_cls, line = _line(item, verdicts, ranks)
                if line_cls == "ai":
                    totals["drafted"] += 1

            rows.append(
                f"<tr><td class='n'>{player['rank']}</td>"
                f"<td>{html_mod.escape(name)}"
                + (f" <span class='flag'>{html_mod.escape(flag)}</span>" if flag else "")
                + "</td>"
                f"<td>{html_mod.escape(player.get('position') or '')}</td>"
                f"<td>{html_mod.escape(player.get('team') or 'FA')}</td>"
                f"<td class='n'>{f'{blend:.1f}' if blend is not None else '—'}</td>"
                f"<td>{wire}</td>"
                f"<td class='{line_cls}'>{html_mod.escape(line) if line else ''}</td></tr>"
            )
        return "".join(rows)

    table_head = (
        "<table><thead><tr><th>#</th><th>Player</th><th>Pos</th><th>Team</th>"
        "<th>ADP</th><th>Latest wire</th><th>Drafted line</th></tr></thead>"
    )
    offense_html = (
        f"<h2 id='offense'>Offense — top {len(offense)}</h2>"
        + table_head
        + f"<tbody>{render_rows(offense)}</tbody></table>"
        if offense
        else ""
    )
    defense_html = (
        f"<h2 id='defense'>Defense — top {len(defense)} (IDP)</h2>"
        + table_head
        + f"<tbody>{render_rows(defense)}</tbody></table>"
        if defense
        else "<h2 id='defense'>Defense</h2><p class='sub'>No defenders in the "
        "stored index yet — the hourly sync refreshes it.</p>"
    )

    return (
        head + f"<p class='sub'><a href='#offense'>Offense ({len(offense)})</a> · "
        f"<a href='#defense'>Defense ({len(defense)})</a> — split so offense "
        "scans clean and defense is one tap away (owner request) · "
        f"{totals['mentioned']} with a wire mention · "
        f"{totals['drafted']} carrying an AI-drafted line · "
        f"{totals['angles']} with an AI angle · "
        f"generated {html_mod.escape(stamp)} · "
        "ranks &amp; injury flags data: Sleeper · wire: ESPN, Yahoo, Rotowire, PFT, CBS · "
        "ADP: FantasyFootballCalculator (10+12tm PPR blend)<br>"
        "AI draft / Auto lines are machine-written and labelled so — the owner's "
        "judgements live on the Alerts tab. The league-scored IDP draft board "
        "lives at /app/idp.</p>" + offense_html + defense_html
    )
