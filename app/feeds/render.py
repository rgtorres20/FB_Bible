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

from . import adp, impact, injury, vegas

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
        label += f" · top-{((rank // 100) + 1) * 100}"
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


def merge_into_feeds(
    bundled: dict,
    items: list[dict],
    now: datetime,
    ranks: dict[str, int] | None = None,
    adp_data: dict | None = None,
    index: dict | None = None,
    verdicts: dict[str, str] | None = None,
    injury_names: tuple[str, ...] | None = None,
    vegas_data: dict | None = None,
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
    # Reading order is impact on the board, decayed by age -- not raw
    # chronology. The unranked full wire stays on /api/feeds.
    kept = impact.order(kept, now)

    live = []
    for item in kept[:MAX_LIVE_ITEMS]:
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
            adp_data.get("state") or {}, adp_data.get("history"), index, kept
        )
    if live_scout:
        merged["scout"] = live_scout

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
        "injury and trending data provided by Sleeper."
    )

    # Data health reads `meta` for its as-of stamps. Without this, that tab
    # keeps reporting News & posts as a chat-synced feed from the day the file
    # was committed -- understating the freshness the overlay just delivered,
    # which is the same class of dishonesty (in the safe direction) that the
    # hardcoded "live" labels were in the unsafe one.
    local_now = now.astimezone(CENTRAL)
    stamp = f"{local_now:%Y-%m-%dT%H:%M}"
    vegas_live = bool((vegas_data or {}).get("games"))
    meta_rows = []
    for entry in bundled.get("meta", []):
        feed = entry.get("feed")
        if feed in ("News & posts", "NBC player news"):
            entry = {
                **entry,
                "asOf": stamp,
                "source": "ESPN, Yahoo, Rotowire, PFT, CBS — live wire",
            }
        elif live_scout and feed in ("Draft board / ADP blend", "Sleeper list"):
            entry = {
                **entry,
                "asOf": stamp,
                "source": "FFC live drafts (10+12tm PPR avg) + Sleeper rank",
            }
        elif vegas_live and feed == "Vegas lines":
            entry = {
                **entry,
                "asOf": vegas.central_stamp((vegas_data or {}).get("fetched_at")) or stamp,
                "source": vegas.LIVE_SOURCE,
            }
        meta_rows.append(entry)
    merged["meta"] = meta_rows
    return merged
