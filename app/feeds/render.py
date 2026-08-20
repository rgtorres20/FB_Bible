"""Render polled items into the shape the app already reads.

The page fetches `data/feeds.json` at startup. Rather than edit a 257KB
generated design document -- which would fork it from the design project and
have to be re-merged forever -- the server serves that same path with live
data in the same shape. The app becomes live without knowing anything changed.

Field shapes were taken from the committed feeds.json, not invented:

    {"kind": "Wire", "handle": "Yahoo lineup wire", "trust": "Tier 1",
     "time": "Fri Aug 14 · 11:00 AM", "text": "...",
     "players": "Malik Willis · QB · MIA"}

Note `players` is a formatted string, not a list, and `time` is Central with
no zero padding. Both matter: the page renders them verbatim.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from . import adp, impact, injury, stats, vegas, weekrev

# The blueprint is explicit that every timestamp renders in the user's zone.
CENTRAL = ZoneInfo("America/Chicago")
DOT = "·"

# The News tab is a reading surface, not an archive. The full set stays at
# /api/feeds for anything that wants it.
MAX_LIVE_ITEMS = 40


def format_time(iso: str | None) -> str:
    """'2026-08-14T16:00:00+00:00' -> 'Fri Aug 14 · 11:00 AM' (Central).

    Built by hand rather than with %-d/%-I, which are not portable to Windows.
    """
    if not iso:
        return ""
    try:
        stamp = datetime.fromisoformat(iso).astimezone(CENTRAL)
    except ValueError:
        return ""
    hour = stamp.hour % 12 or 12
    meridiem = "AM" if stamp.hour < 12 else "PM"
    return f"{stamp:%a} {stamp:%b} {stamp.day} {DOT} {hour}:{stamp:%M} {meridiem}"


def format_players(players: list[dict]) -> str:
    """'Malik Willis · QB · MIA'. Empty when nobody was matched.

    The committed data carries exactly one player per item, so the primary
    match is used; the rest stay available on /api/feeds.
    """
    if not players:
        return ""
    first = players[0]
    parts = [first.get("name", ""), first.get("position", ""), first.get("team") or "FA"]
    return f" {DOT} ".join(p for p in parts if p)


def to_news_entry(item: dict) -> dict:
    """One polled item in the page's news shape."""
    title = (item.get("title") or "").strip()
    summary = (item.get("summary") or "").strip()
    text = f"{title} — {summary}" if summary and summary != title else title

    return {
        "kind": "Wire",
        "handle": item.get("source_name", "Wire"),
        "trust": f"Tier {item.get('tier', 2)}",
        "time": format_time(item.get("published")),
        "text": text,
        "players": format_players(item.get("players") or []),
        # Not in the original shape; the page ignores unknown keys. Kept so a
        # reader can always reach the source, which is also the decent thing
        # to do with someone else's reporting.
        "link": item.get("link", ""),
        # Also ignored by the page's template -- mobile.js reads it to badge
        # what arrived since the owner's last visit.
        "first_seen": item.get("first_seen", ""),
    }


def _lean(item: dict) -> str:
    """Terse right-column call for the NBC tab. Factual, "Auto:" prefixed --
    the curated entries carry real judgements ("Pause at ADP"); ours must
    never dress up as one."""
    category = item.get("impact_category")
    rank = item.get("top_rank")
    label = {
        "severe": "Auto: availability risk",
        "status": "Auto: injury watch",
        "positive": "Auto: positive sign",
    }.get(category, "")
    if not label and rank is not None and rank <= 200:
        label = "Auto: notable"
    if label and rank is not None and rank <= 400:
        label += f" · top-{(((rank - 1) // 100) + 1) * 100}"
    return label


def to_nbc_entry(item: dict) -> dict:
    """One tagged wire item in the NBC player news tab's shape."""
    first = (item.get("players") or [{}])[0]
    title = (item.get("title") or "").strip()
    summary = (item.get("summary") or "").strip()
    return {
        "time": format_time(item.get("published")),
        "player": first.get("name", ""),
        "meta": f"{first.get('position', '')} {DOT} {first.get('team') or 'FA'}",
        "head": title,
        "text": summary if summary and summary != title else title,
        "lean": _lean(item),
        "link": item.get("link", ""),
    }


def rename_leagues(feeds: dict) -> dict:
    """The real league names (docs/LEAGUES.md) in the data file, matching
    the same serve-time pass app/main.py runs on the page: curated alerts,
    scout cards and weekrev star reads still say Sunday Gravy / The
    Trenches on disk. Applied to the whole JSON document at once -- names
    never appear as keys, only inside display strings."""
    import json as _json

    text = _json.dumps(feeds)
    for old, new in (
        ("Sunday Gravy", "NDDPL"),
        ("The Trenches", "RED_EYE"),
        ("Gravy", "NDDPL"),
        ("Trenches", "RED_EYE"),
    ):
        text = text.replace(old, new)
    return _json.loads(text)


def merge_into_feeds(
    bundled: dict,
    items: list[dict],
    now: datetime,
    ranks: dict[str, int] | None = None,
    adp_data: dict | None = None,
    index: dict | None = None,
    verdicts: dict[str, str] | None = None,
    vegas_state: dict | None = None,
    injury_names: tuple[str, ...] | None = None,
    stats_state: dict | None = None,
    mover_reads: dict[str, str] | None = None,
    scores_state: dict | None = None,
) -> dict:
    """Overlay live wire items onto the committed feeds file.

    Only `news` is replaced -- that tab is defined as the raw wire. `alerts`,
    `scout` and the rest carry editorial judgements (status, impact, what it
    means) that a headline cannot supply, so fabricating them would be worse
    than leaving the curated versions in place.

    Before rendering, the wire is scored, deduped and filtered: the same story
    from three outlets folds into one telling, and negative-impact items (the
    Tom Brady broadcasting case) stay on /api/feeds but off the page.
    """
    merged = dict(bundled)
    if not items:
        return merged  # nothing polled yet: serve the committed file untouched

    scored = impact.cluster([impact.score(item, ranks) for item in items])
    kept = [item for item in scored if item["impact_score"] >= 0]
    hidden = len(scored) - len(kept)
    # Impact decides WHAT makes the page: the dedupe, the negative-impact
    # filter, and which MAX_LIVE_ITEMS survive the cut. But the reading
    # order is chronological, newest first -- owner request Aug 20: "i
    # dont want to see updates from 8am next to 8pm". The unranked full
    # wire stays on /api/feeds.
    kept = impact.order(kept, now)
    shown = kept[:MAX_LIVE_ITEMS]
    shown.sort(key=lambda i: i.get("published") or "", reverse=True)

    live = []
    for item in shown:
        entry = to_news_entry(item)
        # {{ a.impact }} renders as the pool feed's WHAT IT MEANS column.
        # Preference order: an AI-drafted verdict (prefixed "AI draft:" --
        # it must never read as the owner's judgement), else the rule-based
        # "Auto:" annotation. Both are honest about their authorship.
        verdict = (verdicts or {}).get(item.get("id", ""))
        entry["impact"] = f"AI draft: {verdict}" if verdict else impact.annotate(item)
        also = item.get("also_from")
        if also:
            entry["text"] += f" (also: {', '.join(also)})"
        live.append(entry)

    # Keep curated entries that the wire has not already said.
    seen = {entry["text"] for entry in live}
    curated = [n for n in bundled.get("news", []) if n.get("text") not in seen]

    merged["news"] = live + curated
    merged["news_hidden_low_impact"] = hidden

    # NBC player news is the other chat-synced news surface, and player-tagged
    # wire items are exactly its genre. Newest first, curated blurbs kept
    # below -- they carry editorial leans a headline cannot replace.
    player_items = [i for i in kept if i.get("players")]
    player_items.sort(key=lambda i: i.get("published") or "", reverse=True)
    nbc_live = [to_nbc_entry(i) for i in player_items[:MAX_LIVE_ITEMS]]
    nbc_seen = {(e["player"], e["head"]) for e in nbc_live}
    nbc_curated = [
        e for e in bundled.get("rotowire", []) if (e.get("player"), e.get("head")) not in nbc_seen
    ]
    merged["rotowire"] = nbc_live + nbc_curated

    # Scout finds: live ADP movers, rank-gap sleepers, and sleeper articles
    # off the wire. Replaces the curated cards only when there is a live board
    # to replace them with -- the fallback rule is the same as everywhere
    # else: stale-but-honest beats blank.
    live_scout = []
    if adp_data:
        live_scout = adp.build_scout(
            adp_data.get("state") or {},
            adp_data.get("history"),
            index,
            kept,
            mover_reads=mover_reads,
        )
    if live_scout:
        merged["scout"] = live_scout

    # Vegas lines: the page's VEGAS constant is rebound to F.vegas at serve
    # time (see app_page), so putting live rows here replaces the committed
    # table. Absent on failure -- the page then falls back to its own seed.
    live_vegas = (vegas_state or {}).get("games") or []
    if live_vegas:
        merged["vegas"] = live_vegas

    # The Week review tab: live scores from the runner-pushed current-week
    # scoreboard, beside the page's own curated high-performer reads. None
    # (no scores yet, or the seed's stars could not be parsed) leaves the
    # committed seed standing whole -- see app/feeds/weekrev.py.
    live_weekrev = weekrev.build(scores_state)
    if live_weekrev:
        merged["weekrev"] = live_weekrev

    # Out & returning is curated in the page and has no timestamps of its
    # own; the freshest wire mention of each listed player is one the server
    # can honestly supply. mobile.js renders these onto the rows. Matched
    # against the full wire, not the impact-filtered cut -- a mention is a
    # mention. The page's template ignores the key.
    if injury_names:
        stamps = injury.wire_stamps(items, injury_names)
        if stamps:
            merged["injury_wire"] = {
                name: {**stamp, "time": format_time(stamp["published"])}
                for name, stamp in stamps.items()
            }

    merged["updated"] = now.isoformat()
    merged["note"] = (
        "News is polled live from ESPN, Yahoo, Rotowire, ProFootballTalk and CBS. "
        "Other feeds are chat-synced. Data provided by the named sources; "
        "injury, trending and season stats data provided by Sleeper."
    )

    # Data health reads `meta` for its as-of stamps. Without this, that tab
    # keeps reporting News & posts as a chat-synced feed from the day the file
    # was committed -- understating the freshness the overlay just delivered,
    # which is the same class of dishonesty (in the safe direction) that the
    # hardcoded "live" labels were in the unsafe one.
    local_now = now.astimezone(CENTRAL)
    stamp = f"{local_now:%Y-%m-%dT%H:%M}"
    live_adp_players = bool(((adp_data or {}).get("state") or {}).get("players"))
    meta_rows = []
    for entry in bundled.get("meta", []):
        feed = entry.get("feed")
        if feed in ("News & posts", "NBC player news"):
            entry = {
                **entry,
                "asOf": stamp,
                "source": "ESPN, Yahoo, Rotowire, PFT, CBS — live wire",
            }
        # Only the draft board actually reads the live blend. The Sleepers
        # tab still renders its committed TARGETS const, so stamping it live
        # alongside the board was this file telling the same lie the board's
        # derived ADP column told -- it keeps its own as-of date until that
        # surface is overlaid too.
        elif live_adp_players and feed == "Draft board / ADP blend":
            entry = {
                **entry,
                "asOf": stamp,
                "source": "FFC live drafts, per league size (12tm / 10tm PPR)",
            }
        elif live_vegas and feed == "Vegas lines":
            label = (vegas_state or {}).get("week_label") or "current slate"
            entry = {
                **entry,
                "asOf": stamp,
                "source": f"DraftKings via ESPN — live, {label}",
            }
        elif feed == "Week 1 schedule" and any(g.get("kickoff") for g in live_vegas):
            entry = {
                **entry,
                "asOf": vegas.central_stamp((vegas_state or {}).get("fetched_at")) or stamp,
                "source": vegas.SCHED_LIVE_SOURCE,
            }
        # Only the usage numbers went live; the '26 win projections on the
        # same tab stay curated, and the label says which is which. Gated on
        # the same all-32-teams check as the serve-time injection, so this
        # row can never claim numbers the page is not actually showing.
        elif feed == "Team intel / projections" and stats.usage_reads(stats_state) is not None:
            entry = {
                **entry,
                "asOf": stamp,
                "source": (
                    "Pass rate + red-zone run share: Sleeper '25 season "
                    "(measured, all 32 teams) · projections still curated"
                ),
            }
        meta_rows.append(entry)
    merged["meta"] = meta_rows
    return merged
