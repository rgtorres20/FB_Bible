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
never on this page. IDP players (DB/LB) are absent because the player index
excludes those positions today — a known gap (GAP_REVIEW #4), stated in the
footer rather than papered over.
"""

from __future__ import annotations

import html as html_mod
from datetime import datetime
from zoneinfo import ZoneInfo

from . import board, impact, render

CENTRAL = ZoneInfo("America/Chicago")

TOP = 300

_STYLE = """
body { font-family: Georgia, 'Times New Roman', serif; margin: 24px;
       color: #16234A; background: #F5F1E6; }
h1 { font-size: 22px; margin: 0 0 2px; }
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
    """Top-300 by Sleeper search rank. Rank ties are broken by id for a
    stable page between renders."""
    players = (index or {}).get("players") or {}
    ranked = [p for p in players.values() if p.get("rank") is not None]
    ranked.sort(key=lambda p: (p["rank"], p.get("id") or ""))
    return ranked[:TOP]


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
) -> str:
    stamp = now.astimezone(CENTRAL).strftime("%a %b %d, %I:%M %p Central")
    head = (
        "<!doctype html><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>FB Bible — top-300 alert board</title>"
        f"<style>{_STYLE}</style>"
        "<h1>Top-300 alert board</h1>"
    )

    players = _ranked_players(index)
    if not players:
        return (
            head + "<p class='sub'>Player index unavailable — the hourly sync "
            f"refreshes it; try again shortly. Checked {html_mod.escape(stamp)}.</p>"
        )

    ranks = {p["id"]: p["rank"] for p in players if p.get("id")}
    mentions = _latest_mentions(items)
    adp = _adp_lookup(adp_state)

    rows = []
    mentioned = drafted = 0
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
            mentioned += 1
            when = render.format_time(item.get("published"))
            source = item.get("source_name") or "wire"
            title = (item.get("title") or "").strip()
            body = html_mod.escape(f"{when} · {source} — {title}")
            link = item.get("link") or ""
            if link:
                body = f"<a href='{html_mod.escape(link, quote=True)}'>{body}</a>"
            wire = f"<span class='wire'>{body}</span>"
            line_cls, line = _line(item, verdicts, ranks)
            if line_cls == "ai":
                drafted += 1

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

    return (
        head + f"<p class='sub'>{len(players)} players by Sleeper fantasy rank · "
        f"{mentioned} with a wire mention · {drafted} carrying an AI-drafted line · "
        f"generated {html_mod.escape(stamp)} · "
        "ranks &amp; injury flags data: Sleeper · wire: ESPN, Yahoo, Rotowire, PFT, CBS · "
        "ADP: FantasyFootballCalculator (10+12tm PPR blend)<br>"
        "AI draft / Auto lines are machine-written and labelled so — the owner's "
        "judgements live on the Alerts tab. DB/LB are absent while the player "
        "index excludes IDP positions (a known gap).</p>"
        "<table><thead><tr><th>#</th><th>Player</th><th>Pos</th><th>Team</th>"
        "<th>ADP</th><th>Latest wire</th><th>Drafted line</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
