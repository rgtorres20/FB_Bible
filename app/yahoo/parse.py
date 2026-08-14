"""Flatten Yahoo's Fantasy JSON into shapes the app can use.

Yahoo's JSON is XML wearing a costume. Two quirks drive everything here:

  1. Collections are objects keyed by stringified indices, with a sibling
     "count":  {"0": {...}, "1": {...}, "count": 2}
  2. A single entity is often a LIST that mixes a list of one-key metadata
     dicts with sibling sub-resource dicts:
     "team": [[{"team_key": ...}, {"name": ...}], {"roster": {...}}]

`normalize` collapses both into ordinary dicts and lists so the extractors
below read like normal code.
"""

from __future__ import annotations

from typing import Any


def _is_indexed_collection(node: dict) -> bool:
    keys = set(node) - {"count"}
    return bool(keys) and all(k.isdigit() for k in keys)


def normalize(node: Any) -> Any:
    """Recursively flatten Yahoo's list/index weirdness."""
    if isinstance(node, dict):
        if _is_indexed_collection(node):
            ordered = sorted((k for k in node if k.isdigit()), key=int)
            return [normalize(node[k]) for k in ordered]
        return {k: normalize(v) for k, v in node.items() if k != "count"}

    if isinstance(node, list):
        items = [normalize(item) for item in node]
        # A list made only of dicts with no key collisions is Yahoo splitting
        # one object across many entries -- merge it back into one dict.
        if items and all(isinstance(i, dict) for i in items):
            merged: dict = {}
            for item in items:
                if any(k in merged for k in item):
                    return items  # real collision: it was genuinely a list
                merged.update(item)
            return merged
        return items

    return node


def content(payload: dict) -> Any:
    """Strip the fantasy_content envelope and normalize what's inside."""
    return normalize(payload.get("fantasy_content", payload))


# --- Domain extractors ----------------------------------------------------
# Each returns plain dicts with only the fields the Fantasy Bible tabs use.


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def parse_leagues(payload: dict) -> list[dict]:
    """From users;use_login=1/games/leagues -> one row per league."""
    root = content(payload)
    games = _as_list(_dig(root, "users", "user", "games"))
    leagues: list[dict] = []
    for game in games:
        game_obj = game.get("game", game) if isinstance(game, dict) else game
        for league in _as_list(_dig(game_obj, "leagues")):
            item = league.get("league", league) if isinstance(league, dict) else league
            if not isinstance(item, dict):
                continue
            leagues.append(
                {
                    "league_key": item.get("league_key"),
                    "league_id": item.get("league_id"),
                    "name": item.get("name"),
                    "num_teams": item.get("num_teams"),
                    "scoring_type": item.get("scoring_type"),
                    "draft_status": item.get("draft_status"),
                    "current_week": item.get("current_week"),
                    "season": item.get("season"),
                    "url": item.get("url"),
                }
            )
    return leagues


def parse_roster(payload: dict) -> list[dict]:
    """From team/{key}/roster -> one row per rostered player."""
    root = content(payload)
    team = _dig(root, "team") or {}
    players = _as_list(_dig(team, "roster", "players"))
    return [_player_row(p) for p in players if isinstance(p, dict)]


def parse_draft_results(payload: dict) -> list[dict]:
    """From league/{key}/draftresults -> one row per pick, in pick order."""
    root = content(payload)
    picks = _as_list(_dig(root, "league", "draft_results"))
    rows = []
    for entry in picks:
        pick = entry.get("draft_result", entry) if isinstance(entry, dict) else entry
        if not isinstance(pick, dict):
            continue
        rows.append(
            {
                "pick": pick.get("pick"),
                "round": pick.get("round"),
                "team_key": pick.get("team_key"),
                "player_key": pick.get("player_key"),
            }
        )
    return sorted(rows, key=lambda r: int(r["pick"]) if r.get("pick") else 0)


def _player_row(entry: dict) -> dict:
    player = entry.get("player", entry)
    if isinstance(player, list):
        player = normalize(player)
    name = player.get("name") or {}
    return {
        "player_key": player.get("player_key"),
        "player_id": player.get("player_id"),
        "name": name.get("full") if isinstance(name, dict) else name,
        "team": player.get("editorial_team_abbr"),
        "position": player.get("display_position"),
        "status": player.get("status"),  # e.g. Q, IR, O
        "status_full": player.get("status_full"),
        "injury_note": player.get("injury_note"),
        "selected_position": _selected_position(player),
        "bye_week": _dig(player, "bye_weeks", "week"),
    }


def _selected_position(player: dict) -> str | None:
    selected = player.get("selected_position")
    if isinstance(selected, dict):
        return selected.get("position")
    return None


def _dig(node: Any, *keys: str) -> Any:
    """Walk nested keys, returning None the moment the path breaks."""
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node
