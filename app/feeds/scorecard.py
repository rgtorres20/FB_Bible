"""Did the calls turn out to be right?

Owner ask, Aug 21, after "how can we improve our AI predictions — could
we use 2 models?". A second model buys agreement, not accuracy: both read
the same inputs and both regress to the same conventional wisdom. The
thing nothing in this app has ever done is check whether a call was
*right*, and until that exists there is no way to tell whether any change
— a second model, a better prompt, more evidence — helped or hurt.

So: a ledger.

**Recording is separate from grading, and that is the whole design.** A
prediction you can edit after you know the answer is not a prediction.
Every lean is snapshotted the moment it is made, keyed by season, week,
player and prop, and an existing key is *never* overwritten — not by a
line move, not by a re-run, not by a better idea. Grading happens later,
against real box scores, and only fills in the outcome.

What is gradeable and what is not, decided honestly:

  * **TD-lean props are gradeable.** "Passing TDs over 1.5" is a claim
    that a box score settles. Those are recorded and graded.
  * **Capsules, verdicts, mover reads and previews are not.** They are
    prose, and inventing a rubric to score prose would produce a number
    that looks like a measurement and is not one. They stay unscored, and
    the page says so rather than quietly implying full coverage.

The output that matters is not the hit rate — it is **calibration**. A
row carries a confidence, so the real question is whether 70% means 70%.
A model that is right 60% of the time and says so is more useful than one
that is right 65% of the time and always claims 85%.
"""

from __future__ import annotations

import logging

from .. import config
from . import players as players_mod

log = logging.getLogger(__name__)

LEDGER_VERSION = 1

# Which Sleeper stat settles each prop. Names are the page's own prop
# labels; the fields were verified against the live dump's field census
# (probe runs 5 and 9) before anything was scored against them.
PROP_FIELDS = {
    "Passing TDs": "pass_td",
    "Rushing TDs": "rush_td",
    "Receiving TDs": "rec_td",
    "Passing Yards": "pass_yd",
    "Rushing Yards": "rush_yd",
    "Receiving Yards": "rec_yd",
    "Receptions": "rec",
}

# Confidence bands the calibration table reports. Wide on purpose: with a
# season's worth of leans, narrower buckets hold too few rows to say
# anything, and a bucket of three is noise wearing a percentage.
BANDS = ((50, 59), (60, 69), (70, 79), (80, 100))


# The season these predictions are about. Sourced from the odds module so
# there is one place to change it, not two that can disagree.
SEASON = config.SEASON_YEAR


def current_week(scores_state: dict | None) -> tuple[int | None, str]:
    """Which regular-season week the app is in, from the pushed scoreboard.

    Returns (None, reason) during the preseason, which is the whole point
    of returning a reason: nothing gets recorded and nothing gets graded
    until real games are played, and the page says which it is rather
    than showing an accuracy over zero games.
    """
    label = str((scores_state or {}).get("week_label") or "").strip()
    if not label:
        return None, "no scoreboard pushed yet"
    if "pre" in label.lower():
        return None, f"preseason ({label}) — regular-season games have not started"
    digits = "".join(ch for ch in label if ch.isdigit())
    if not digits:
        return None, f"could not read a week number from {label!r}"
    return int(digits), label


def blank() -> dict:
    return {"v": LEDGER_VERSION, "entries": []}


def _key(season: int, week: int, entry: dict) -> str:
    parts = (season, week, entry.get("name", ""), entry.get("prop", ""), entry.get("line", ""))
    return "|".join(str(part) for part in parts)


def record(
    ledger: dict | None,
    predictions: list[dict],
    season: int,
    week: int,
    stamped_at: str,
) -> tuple[dict, int]:
    """Snapshot this week's leans. Returns (ledger, how many were new).

    Idempotent by construction: an entry whose key already exists is left
    exactly as first written. That is what makes the ledger evidence
    rather than a changing opinion -- re-running the sync twenty times a
    day must not let a call drift toward whatever is currently true.
    """
    ledger = dict(ledger or blank())
    entries = list(ledger.get("entries") or [])
    seen = {e.get("key") for e in entries}

    added = 0
    for pred in predictions or []:
        key = _key(season, week, pred)
        if key in seen:
            continue
        try:
            line = float(pred.get("line"))
        except (TypeError, ValueError):
            continue
        lean = (pred.get("lean") or "").strip().upper()
        if lean not in {"OVER", "UNDER"} or pred.get("prop") not in PROP_FIELDS:
            continue
        entries.append(
            {
                "key": key,
                "season": season,
                "week": week,
                "name": pred.get("name") or "",
                "meta": pred.get("meta") or "",
                "prop": pred.get("prop"),
                "line": line,
                "lean": lean,
                # The confidence AS SHOWN, after any line-move
                # adjustment -- calibration has to score what the reader
                # actually saw, not the number before the adjustment.
                "conf": int(pred.get("conf") or 0),
                "recorded_at": stamped_at,
                "result": None,
                "actual": None,
            }
        )
        seen.add(key)
        added += 1

    ledger["entries"] = entries
    ledger["v"] = LEDGER_VERSION
    return ledger, added


def _resolve(entry: dict, actual: float) -> str:
    line, lean = entry["line"], entry["lean"]
    if actual == line:
        # Impossible on a half-point line, real on a whole number, and a
        # push is not a win. Scored as void so it cannot flatter the rate.
        return "push"
    over = actual > line
    return "hit" if (over == (lean == "OVER")) else "miss"


def grade(
    ledger: dict | None,
    week_stats: dict | None,
    ids_by_name: dict[str, str],
    season: int,
    week: int,
) -> tuple[dict, int]:
    """Settle this week's open entries against real box scores.

    Only entries for the given week, only ones still open, and only where
    the player's line exists -- a player who did not appear stays open
    rather than being scored a miss, because "did not play" is not a
    wrong call about what he would do if he did.
    """
    ledger = dict(ledger or blank())
    entries = [dict(e) for e in (ledger.get("entries") or [])]
    stats = (week_stats or {}).get("players") or week_stats or {}

    settled = 0
    for entry in entries:
        if entry.get("result") or entry.get("season") != season or entry.get("week") != week:
            continue
        pid = ids_by_name.get(_norm(entry.get("name", "")))
        line = (stats.get(pid) or {}) if pid else {}
        # "Played" is gp, not the entry existing: Sleeper's dumps carry
        # rank-only entries for players with no games at all.
        if not line or not line.get("gp"):
            continue
        field = PROP_FIELDS.get(entry.get("prop", ""))
        if field is None:
            continue
        # Sleeper omits zero-valued fields (verified live, probe run 12:
        # 128 pass_att holders, 97 pass_td). A quarterback who played and
        # threw no touchdown has no pass_td key -- and he is exactly the
        # game that settles an under. Absent-but-played reads as 0;
        # requiring the key kept the strongest unders open forever, which
        # quietly biased every rate this page reports.
        actual = float(line.get(field) or 0)
        entry["actual"] = actual
        entry["result"] = _resolve(entry, actual)
        settled += 1

    ledger["entries"] = entries
    return ledger, settled


# The graders join predictions to box scores by name, so they use the
# kernel's one join key rather than a private cleaner. The private one
# stripped the straight apostrophe and kept the curly, and Sleeper writes
# the curly -- so every lean on a Ja'Marr Chase could be recorded and
# never settled, an entry stuck open forever with the answer sitting in
# the box score.
_norm = players_mod.match_key


def name_index(index: dict | None) -> dict[str, str]:
    """{normalised name: player id} for the graders' join."""
    out = {}
    for pid, player in ((index or {}).get("players") or {}).items():
        if player.get("dst"):
            continue
        name = _norm(player.get("name") or "")
        if name and name not in out:
            out[name] = pid
    return out


def summary(ledger: dict | None) -> dict:
    """The record, and the calibration table that is the actual point.

    Every count is of *settled* entries. Open and pushed rows are
    reported separately rather than folded in, because a hit rate that
    quietly counts unplayed games is the exact false positive this whole
    project is built to refuse.
    """
    entries = (ledger or {}).get("entries") or []
    settled = [e for e in entries if e.get("result") in {"hit", "miss"}]
    hits = sum(1 for e in settled if e["result"] == "hit")

    by_prop: dict[str, dict] = {}
    for entry in settled:
        row = by_prop.setdefault(entry["prop"], {"n": 0, "hits": 0})
        row["n"] += 1
        row["hits"] += entry["result"] == "hit"

    bands = []
    for low, high in BANDS:
        rows = [e for e in settled if low <= e.get("conf", 0) <= high]
        bands.append(
            {
                "label": f"{low}–{high}%",
                "n": len(rows),
                "hits": sum(1 for e in rows if e["result"] == "hit"),
                # What the app claimed, averaged, so "said 72, hit 58" is
                # readable straight off the row.
                "claimed": round(sum(e.get("conf", 0) for e in rows) / len(rows)) if rows else None,
                "actual": round(100 * sum(1 for e in rows if e["result"] == "hit") / len(rows))
                if rows
                else None,
            }
        )

    weeks = sorted({(e.get("season"), e.get("week")) for e in entries})
    return {
        "recorded": len(entries),
        "settled": len(settled),
        "open": sum(1 for e in entries if not e.get("result")),
        "pushed": sum(1 for e in entries if e.get("result") == "push"),
        "hits": hits,
        "rate": round(100 * hits / len(settled)) if settled else None,
        "by_prop": by_prop,
        "bands": bands,
        "weeks": weeks,
    }
