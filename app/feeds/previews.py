"""Week 1 matchup previews: the market meets the '25 offense profiles.

One short AI read per game on the schedule tab, built from two things we
already hold: the pushed Vegas slate (favorite, total, per-side implied
points) and the '25 team-offense aggregates (pass rate, red-zone run
share, red-zone conversion). The server assembles the work list so the
model can only cite numbers we fetched, and the clause renders appended
to the schedule row's note prefixed "AI preview:" — labelled machine
writing beside the owner's own note, never blended into it.

Freshness is snapshot-based, the same idea as capsule wire_ids: each
stored preview remembers the total and favorite it was drafted against,
and the game re-queues when the line has genuinely moved — a preview
citing a 44.5 total must not outlive a 48.5 line.
"""

from __future__ import annotations

from . import vegas
from .stats import _USAGE_FIELDS as _TEAM_USAGE_FIELDS

# Two short sentences' worth, appended to a schedule note cell.
MAX_CHARS = 220
# A stored preview survives line drift below this; at or past it the game
# re-queues so the prose never cites a number the table no longer shows.
REFRESH_TOTAL_DELTA = 1.0


def _team_profile(teams: dict, code: str) -> dict | None:
    """The '25 offense derivations for one team, or None when the season
    aggregates are incomplete — the model is told only what we measured."""
    entry = teams.get(code) or {}
    if not all(entry.get(f) for f in _TEAM_USAGE_FIELDS):
        return None
    plays = entry["pass_att"] + entry["rush_att"]
    rz_plays = entry["pass_rz_att"] + entry["rush_rz_att"]
    profile = {
        "pass_rate_pct": round(100 * entry["pass_att"] / plays),
        "rz_run_share_pct": round(100 * entry["rush_rz_att"] / rz_plays),
    }
    rz_att, rz_conv = entry.get("rz_att"), entry.get("rz_conv")
    if rz_att and isinstance(rz_conv, int | float):
        profile["rz_trips"] = rz_att
        profile["rz_td_pct"] = round(100 * rz_conv / rz_att)
    return profile


def _codes(row: dict) -> tuple[str, str] | None:
    return vegas.matchup_teams(row.get("game"))


def is_covered(preview: dict | None, row: dict) -> bool:
    """A preview covers its game until the line genuinely moves."""
    if not preview:
        return False
    if (preview.get("fav") or "") != (row.get("fav") or ""):
        return False

    def _total(value) -> float | None:
        try:
            return float(value or "")
        except ValueError:
            return None

    stored, current = _total(preview.get("total")), _total(row.get("total"))
    if stored is None and current is not None:
        # The preview was written before the book posted a line; a real
        # total arriving IS the line moving. Treating "unparseable on
        # either side" as covered kept the lineless preview forever.
        return False
    if stored is None or current is None:
        # Still no line, or the line was pulled: nothing moved that we
        # can see.
        return True
    return abs(stored - current) < REFRESH_TOTAL_DELTA


def pending(
    vegas_state: dict | None,
    stats_state: dict | None,
    previews: dict | None,
    implied: dict[str, float] | None = None,
) -> list[dict]:
    """Games still needing a preview, each carrying every number the model
    is allowed to use. One batched call covers the whole slate.

    `implied` is passed in by the composer rather than derived here: this
    module is an AI unit and the odds unit is its sideways neighbour, so
    reaching for it directly was a boundary breach
    (tests/test_boundaries.py, Aug 21). Omitted, it falls back to the odds
    unit so nothing that already calls this two-argument breaks.
    """
    games = (vegas_state or {}).get("games") or []
    previews = previews or {}
    teams = (stats_state or {}).get("teams") or {}
    if implied is None:
        implied = vegas.implied_by_team(games)

    work = []
    for row in games:
        key = row.get("game") or ""
        codes = _codes(row)
        if not key or not codes or is_covered(previews.get(key), row):
            continue
        away, home = codes
        entry: dict = {"game": key}
        for field in ("fav", "total"):
            if row.get(field):
                entry[field] = row[field]
        sides = {}
        for code in (away, home):
            side: dict = {}
            if code in implied:
                side["implied_points"] = implied[code]
            profile = _team_profile(teams, code)
            if profile:
                side["offense_2025"] = profile
            if side:
                sides[code] = side
        if not sides:
            continue  # no line and no measured profile: nothing to say
        entry["teams"] = sides
        work.append(entry)
    return work


def accept(payload: dict[str, str], vegas_state: dict | None, existing: dict | None) -> dict:
    """Merge posted previews over the stored ones, admitting only games the
    slate holds — the model cannot invent a matchup — each snapshotting the
    line it was drafted against, and pruning games that left the slate."""
    rows = {r.get("game"): r for r in (vegas_state or {}).get("games") or [] if r.get("game")}
    merged = dict(existing or {})
    for key, text in payload.items():
        row = rows.get(key)
        clean = str(text or "").strip()[:MAX_CHARS]
        if row is None or not clean:
            continue
        merged[key] = {
            "text": clean,
            "total": str(row.get("total") or ""),
            "fav": str(row.get("fav") or ""),
        }
    return {key: p for key, p in merged.items() if key in rows}


def by_matchup(vegas_state: dict | None, previews: dict | None) -> dict[str, str]:
    """Preview text keyed the way schedule rows are: 'Away Name @ Home Name'."""
    out: dict[str, str] = {}
    for row in (vegas_state or {}).get("games") or []:
        preview = (previews or {}).get(row.get("game") or "")
        away, home = row.get("away_name") or "", row.get("home_name") or ""
        if preview and away and home:
            out[f"{away} @ {home}"] = preview["text"]
    return out
