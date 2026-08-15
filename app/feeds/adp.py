"""Live draft-room ADP, blended for the owner's two leagues.

FantasyFootballCalculator publishes real mock-draft ADP as free JSON, keyed
by league size and scoring. Both of the owner's leagues are full PPR but at
different sizes -- Sunday Gravy is 12-team, The Trenches is 10-team -- so the
board the app shows is the average of the two, not either one alone.

Movement needs memory: FFC reports where the market is today, not where it
was last week. Each sync stores one snapshot per calendar day in the feed
store, and risers/fallers are computed against the oldest snapshot within the
window. Until enough days accumulate, the movers section is simply absent --
an empty truthful section beats a fabricated trend.

"Sleeper finds" come from disagreement between two free signals we already
hold: Sleeper's search rank (the crowd's consensus of who matters) versus the
blended ADP (where draft rooms actually take them). A player ranked far ahead
of his draft slot is value the room has not priced in yet.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta

import httpx

from . import players as players_mod

log = logging.getLogger(__name__)

ADP_URL = "https://fantasyfootballcalculator.com/api/v1/adp/ppr"
# Sunday Gravy (12-team PPR) and The Trenches (10-team PPR).
LEAGUE_SIZES = (12, 10)

MAX_BOARD = 220  # deep enough for a 15-round 12-teamer with margin
MAX_HISTORY_DAYS = 10
MOVER_WINDOW = timedelta(days=8)
MOVER_MIN_DELTA = 4.0  # ADP spots; below this is draft-to-draft noise
MAX_RISERS = 6
MAX_FALLERS = 4
SLEEPER_MAX_RANK = 150
SLEEPER_MIN_GAP = 25.0
MAX_SLEEPER_FINDS = 6
MAX_ARTICLE_FINDS = 4

_SLEEPER_WORD = re.compile(r"\bsleepers?\b", re.IGNORECASE)


async def fetch(client: httpx.AsyncClient | None = None) -> dict:
    """Fetch FFC ADP for both league sizes and blend them.

    Returns the adp state dict stored alongside the news payload:
    {"fetched_at", "date", "players": [...]} -- history is managed separately
    by update_history so a failed fetch never truncates it.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(
            timeout=30.0, headers={"User-Agent": "FBBible/1.0 (draft prep, hourly)"}
        )
    try:
        by_size: dict[int, list[dict]] = {}
        for size in LEAGUE_SIZES:
            resp = await client.get(ADP_URL, params={"teams": size, "year": 2026})
            resp.raise_for_status()
            payload = resp.json()
            rows = payload.get("players") or []
            if not rows:
                raise ValueError(f"FFC returned 0 players for {size}-team")
            by_size[size] = rows
    finally:
        if own_client:
            await client.aclose()

    now = datetime.now(UTC)
    return {
        "fetched_at": now.isoformat(),
        "date": f"{now:%Y-%m-%d}",
        "players": blend(by_size),
    }


def blend(by_size: dict[int, list[dict]]) -> list[dict]:
    """Average ADP across league sizes; players missing from one size keep the
    other's number rather than being dropped -- late-round names appear in the
    deeper format first."""
    merged: dict[str, dict] = {}
    for size, rows in by_size.items():
        for row in rows:
            name = (row.get("name") or "").strip()
            adp = row.get("adp")
            if not name or not isinstance(adp, int | float):
                continue
            entry = merged.setdefault(
                name,
                {
                    "name": name,
                    "position": row.get("position") or "",
                    "team": row.get("team") or "",
                    "bye": row.get("bye"),
                    "sizes": {},
                },
            )
            entry["sizes"][str(size)] = round(float(adp), 1)

    out = []
    for entry in merged.values():
        values = list(entry["sizes"].values())
        entry["adp"] = round(sum(values) / len(values), 1)
        out.append(entry)
    out.sort(key=lambda e: e["adp"])
    return out[:MAX_BOARD]


def update_history(history: list[dict] | None, state: dict) -> list[dict]:
    """One snapshot per calendar day, newest last, capped.

    Snapshots hold only {name: adp} -- enough to diff, small enough that ten
    days of top-220 boards stay far under any Redis free-tier ceiling.
    """
    history = [h for h in (history or []) if h.get("date") and h.get("adp")]
    snapshot = {p["name"]: p["adp"] for p in state.get("players", [])}
    if not snapshot:
        return history
    history = [h for h in history if h["date"] != state["date"]]
    history.append({"date": state["date"], "adp": snapshot})
    history.sort(key=lambda h: h["date"])
    return history[-MAX_HISTORY_DAYS:]


def _baseline(history: list[dict], today: str) -> dict | None:
    """Oldest snapshot within the mover window that is not today's."""
    try:
        today_dt = datetime.strptime(today, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None
    for h in history:  # sorted oldest-first
        if h["date"] == today:
            continue
        try:
            age = today_dt - datetime.strptime(h["date"], "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            continue
        if timedelta(days=0) < age <= MOVER_WINDOW:
            return h
    return None


def _rank_lookup(index: dict | None) -> dict[str, int]:
    """Sleeper search rank keyed by normalized name."""
    ranks: dict[str, int] = {}
    for player in (index or {}).get("players", {}).values():
        rank = player.get("rank")
        name = player.get("name")
        if rank is not None and name:
            key = " ".join(players_mod.normalize(name).split())
            ranks.setdefault(key, rank)
    return ranks


def _meta(entry: dict) -> str:
    pos = entry.get("position") or "?"
    team = entry.get("team") or "FA"
    return f"{pos} · {team}"


def build_scout(
    state: dict,
    history: list[dict] | None = None,
    index: dict | None = None,
    items: list[dict] | None = None,
) -> list[dict]:
    """Live Scout-finds entries in the page's own card shape.

    Order matters for the tab's default "All" view: movers first (they are
    the perishable signal), then rank-gap sleepers, then sleeper articles off
    the wire.
    """
    board = state.get("players") or []
    if not board:
        return []
    date = state.get("date") or ""
    src_movers = f"FFC live drafts (10+12tm PPR avg) · {date}"

    entries: list[dict] = []

    base = _baseline(history or [], date)
    if base:
        movers = []
        for entry in board:
            old = base["adp"].get(entry["name"])
            if old is None:
                continue
            movers.append((old - entry["adp"], old, entry))
        movers.sort(key=lambda m: m[0], reverse=True)
        days = (
            datetime.strptime(date, "%Y-%m-%d") - datetime.strptime(base["date"], "%Y-%m-%d")
        ).days

        for delta, old, entry in movers[:MAX_RISERS]:
            if delta < MOVER_MIN_DELTA:
                break
            entries.append(
                {
                    "kind": "ADP riser",
                    "name": entry["name"],
                    "meta": _meta(entry),
                    "pos": entry.get("position") or "",
                    "text": f"{old:.1f} → {entry['adp']:.1f} over {days}d of live drafts "
                    f"— up {delta:.0f} spots.",
                    "src": src_movers,
                }
            )
        for delta, old, entry in sorted(movers, key=lambda m: m[0])[:MAX_FALLERS]:
            if -delta < MOVER_MIN_DELTA:
                break
            entries.append(
                {
                    "kind": "ADP faller",
                    "name": entry["name"],
                    "meta": _meta(entry),
                    "pos": entry.get("position") or "",
                    "text": f"{old:.1f} → {entry['adp']:.1f} over {days}d "
                    f"— down {-delta:.0f} spots.",
                    "src": src_movers,
                }
            )

    ranks = _rank_lookup(index)
    if ranks:
        finds = []
        for entry in board:
            key = " ".join(players_mod.normalize(entry["name"]).split())
            rank = ranks.get(key)
            if rank is None or rank > SLEEPER_MAX_RANK:
                continue
            gap = entry["adp"] - rank
            if gap >= SLEEPER_MIN_GAP:
                finds.append((gap, rank, entry))
        finds.sort(key=lambda f: f[0], reverse=True)
        for gap, rank, entry in finds[:MAX_SLEEPER_FINDS]:
            entries.append(
                {
                    "kind": "Sleeper find",
                    "name": entry["name"],
                    "meta": _meta(entry),
                    "pos": entry.get("position") or "",
                    "text": f"Sleeper consensus has him #{rank}; draft rooms take him at "
                    f"{entry['adp']:.0f} — the market is ~{gap:.0f} picks behind.",
                    "src": "Sleeper rank vs FFC ADP",
                }
            )

    for item in _article_finds(items or []):
        entries.append(item)

    return entries


def _article_finds(items: list[dict]) -> list[dict]:
    """Sleeper articles off the wire we already poll -- the free version of
    'search the web for sleepers': every outlet publishes these in August."""
    found = []
    seen = set()
    for item in sorted(items, key=lambda i: i.get("published") or "", reverse=True):
        text = f"{item.get('title') or ''} {item.get('summary') or ''}"
        if not _SLEEPER_WORD.search(text):
            continue
        tagged = item.get("players") or []
        name = tagged[0].get("name") if tagged else (item.get("title") or "").strip()[:60]
        if not name or name in seen:
            continue
        seen.add(name)
        meta = (
            f"{tagged[0].get('position') or '?'} · {tagged[0].get('team') or 'FA'}"
            if tagged
            else "article"
        )
        found.append(
            {
                "kind": "Sleeper find",
                "name": name,
                "meta": meta,
                "pos": tagged[0].get("position") or "" if tagged else "",
                "text": (item.get("title") or "").strip(),
                "src": f"{item.get('source_name', 'wire')} · sleeper coverage",
            }
        )
        if len(found) >= MAX_ARTICLE_FINDS:
            break
    return found
