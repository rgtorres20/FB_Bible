"""Per-player AI capsules for the top-300 alert board.

The board's drafted line is per *wire item*: a player with no news shows
nothing, and a player with news shows a line about that one story. A
capsule is the per-*player* synthesis — his Sleeper rank, his live ADP,
his '25 usage numbers, his injury flag and his newest wire word, blended
into one sentence — rendered "AI angle:" so it never reads as the owner's
judgement.

Grounding rule, same as every AI surface here: **the model never recalls
a number, it only reads ones we fetched.** This module assembles the
work list server-side, so every figure in the prompt came out of our own
store; the hourly script just relays it. Coverage accumulates the way
verdicts do — each hour's one request goes to uncovered players, best
rank first — and a capsule refreshes when its player's newest wire item
changes, so a stale synthesis does not outlive the news it cites.
"""

from __future__ import annotations

from . import render
from .alerts300 import _adp_lookup, _latest_mentions, _ranked_players
from .board import match_key

# One board column's worth of text, a shade longer than a mover clause.
MAX_CHARS = 160
# One batched request an hour covers the 300 in about a day.
BATCH = 16
MAX_WIRE_ID = 64

# Usage fields worth putting in front of the model, in the order a reader
# would cite them. Only fields the player actually holds are sent — the
# stats extractor counts coverage per field and nothing here assumes one.
_USAGE_FIELDS = (
    "gp",
    "rush_att",
    "rush_rz_att",
    "rush_td",
    "rec_tgt",
    "rec_rz_tgt",
    "rec",
    "rec_td",
    "pass_att",
)


def _usage(stats_state: dict | None, pid: str) -> dict:
    """The player's '25 usage line, present fields only, plus snap share
    when both halves of the ratio exist."""
    entry = ((stats_state or {}).get("players") or {}).get(pid) or {}
    out = {f: entry[f] for f in _USAGE_FIELDS if isinstance(entry.get(f), int | float)}
    snaps, team_snaps = entry.get("off_snp"), entry.get("tm_off_snp")
    if isinstance(snaps, int | float) and isinstance(team_snaps, int | float) and team_snaps:
        out["snap_pct"] = round(100 * snaps / team_snaps)
    return out


def is_covered(capsule: dict | None, newest_item: dict | None) -> bool:
    """A capsule covers its player until the newest wire item changes."""
    if not capsule:
        return False
    newest_id = (newest_item or {}).get("id") or ""
    return capsule.get("wire_id", "") == newest_id


def pending(
    index: dict | None,
    adp_state: dict | None,
    stats_state: dict | None,
    items: list[dict],
    capsules: dict[str, dict] | None,
    limit: int = BATCH,
) -> list[dict]:
    """The next batch of capsule work: uncovered top-300 players, best rank
    first, each carrying every number the model is allowed to use."""
    capsules = capsules or {}
    mentions = _latest_mentions(items)
    adp = _adp_lookup(adp_state)

    work = []
    for player in _ranked_players(index):
        pid = player.get("id") or ""
        if not pid:
            continue
        newest = mentions.get(pid)
        if is_covered(capsules.get(pid), newest):
            continue

        blend = adp.get(match_key(player.get("name") or ""))
        entry: dict = {
            "id": pid,
            "name": player.get("name") or "",
            "position": player.get("position") or "",
            "team": player.get("team") or "FA",
            "sleeper_rank": player["rank"],
        }
        flag = (player.get("injury_status") or "").strip()
        if flag:
            entry["injury"] = flag
        if blend is not None:
            entry["live_adp"] = blend
        usage = _usage(stats_state, pid)
        if usage:
            entry["usage_2025"] = usage
        if newest is not None:
            entry["newest_wire"] = {
                "id": newest.get("id") or "",
                "when": render.format_time(newest.get("published")),
                "source": newest.get("source_name") or "wire",
                "title": (newest.get("title") or "").strip(),
            }
        work.append(entry)
        if len(work) >= limit:
            break
    return work


def accept(
    payload: dict[str, dict],
    index: dict | None,
    existing: dict[str, dict] | None,
) -> dict[str, dict]:
    """Merge posted capsules over the stored ones, admitting only players
    the index ranks in the top 300 — the model cannot add a row to the
    board by inventing an id — and pruning anyone who fell out of it."""
    ranked_ids = {p.get("id") for p in _ranked_players(index)}
    merged = dict(existing or {})
    for pid, capsule in payload.items():
        if pid not in ranked_ids or not isinstance(capsule, dict):
            continue
        text = str(capsule.get("text") or "").strip()[:MAX_CHARS]
        if not text:
            continue
        merged[pid] = {
            "text": text,
            "wire_id": str(capsule.get("wire_id") or "")[:MAX_WIRE_ID],
        }
    return {pid: c for pid, c in merged.items() if pid in ranked_ids}
