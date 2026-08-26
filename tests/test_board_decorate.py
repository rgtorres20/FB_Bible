"""Membership first, decoration second.

The board's two decorations -- `'25 P/G` and the injury badge -- are maps
keyed by player name, looked up at runtime by exact match. `drop_reserve`
removes rows and `deepen` appends them, so a map built at the wrong point
in the pipeline is wrong in one of two ways:

- built before the drop, it carries keys for players no longer on the
  board -- dead weight, and proof the order is not being thought about;
- built before the deepening, it never reaches the appended rows at all,
  which is roughly a third of the served board.

Both were happening in `main` until Aug 22, when the live watchdog's new
"every scored player is a row the board can look up" check failed on its
first run with five orphaned keys. The bigger half was silent: every
appended depth row rendered a dash for points and wore no badge.

`board.decorate` owns the order now so this test can pin it.
"""

from __future__ import annotations

import json
import re

from app import leagues as leagues_mod
from app.feeds import board

INDEX_HTML = open("frontend/index.html", encoding="utf-8").read()
LEAGUES = leagues_mod.defaults()


def _row_names(html: str) -> list[str]:
    block = re.search(r"const RAW_BOARD = \[(.*?)\n\];", html, re.S)
    return re.findall(r'^\s*\[\d+,"([^"]+)"', block.group(1), re.M) if block else []


def _map(html: str, const: str) -> dict:
    found = re.search(rf"const {const} = (\{{.*?\}});\n", html, re.S)
    return json.loads(found.group(1)) if found else {}


def _index_from_page(html: str, extra: list[dict] | None = None) -> dict:
    """An index covering the real board plus whatever a case adds."""
    players = {}
    for i, name in enumerate(_row_names(html)):
        players[str(i)] = {
            "id": str(i),
            "name": name,
            "position": "WR",
            "team": "NYG",
            "injury_status": None,
            "rank": i + 1,
        }
    for j, player in enumerate(extra or []):
        players[f"x{j}"] = player
    return {"players": players}


def _stats_for(index: dict) -> dict:
    return {
        "players": {
            pid: {"gp": 17, "rec": 80, "rec_yd": 1000, "rec_td": 6}
            if p["position"] == "WR"
            else {"gp": 17, "idp_tkl_solo": 60, "idp_tkl_ast": 20}
            for pid, p in index["players"].items()
        }
    }


def test_no_decoration_key_points_at_a_row_that_is_gone():
    """The watchdog check, run here so it fails in CI rather than live.

    A player on IR is dropped from the board; his points entry must go
    with him. Before the fix the map was built first and kept the key.
    """
    index = _index_from_page(INDEX_HTML)
    hurt = next(iter(index["players"].values()))
    hurt["injury_status"] = "IR"
    out, marks = board.decorate(INDEX_HTML, index, _stats_for(index), LEAGUES)

    assert marks["benched"] == [hurt["name"]]
    rows = set(_row_names(out))
    assert hurt["name"] not in rows
    assert set(_map(out, "FB_LEAGUE_PTS")) <= rows
    assert set(_map(out, "FB_INJURIES")) <= rows
    assert hurt["name"] not in _map(out, "FB_LEAGUE_PTS")


def test_the_rows_deepen_appends_are_decorated_too():
    """The silent half. Appended depth is a third of the served board and
    it rendered a dash for points and no badge for injury."""
    extra = [
        {
            "id": "x0",
            "name": "Depth Linebacker",
            "position": "LB",
            "team": "CHI",
            "injury_status": "Questionable",
            "rank": 240,
            "idp": "LB",
        }
    ]
    index = _index_from_page(INDEX_HTML, extra)
    out, marks = board.decorate(INDEX_HTML, index, _stats_for(index), LEAGUES)

    assert marks["deepened"] > 0
    assert "Depth Linebacker" in _row_names(out)
    assert "Depth Linebacker" in _map(out, "FB_LEAGUE_PTS")
    assert _map(out, "FB_INJURIES")["Depth Linebacker"]["flag"] == "Questionable"


def test_every_decorated_name_is_a_row_on_the_finished_board():
    """The invariant itself, over the whole real board -- no orphans in
    either direction, whatever the fixture happens to contain."""
    index = _index_from_page(INDEX_HTML)
    out, _ = board.decorate(INDEX_HTML, index, _stats_for(index), LEAGUES)
    rows = set(_row_names(out))
    assert _map(out, "FB_LEAGUE_PTS")
    assert set(_map(out, "FB_LEAGUE_PTS")) <= rows
    assert set(_map(out, "FB_INJURIES")) <= rows


def test_a_missing_index_clears_the_badges_rather_than_keeping_frozen_ones():
    """No index means nothing is dropped, nothing is appended and nothing
    is scored -- but the frozen name lists still go, and every badge with
    them.

    Deliberate, and worth knowing: during an index outage the board shows
    no injury badge at all, which reads as "everybody is healthy". The
    alternative is worse -- the committed lists are hand-typed and weeks
    stale, and asserting a stale status is the failure this replaced. A
    third option, saying status is unavailable, does not exist yet
    (docs/ASSUMPTIONS.md).
    """
    out, marks = board.decorate(INDEX_HTML, None, None, LEAGUES)
    # blend_wired is 1 even here, and should be: making the Blend column
    # the number the board sorts by is a rewiring of the page's own
    # arithmetic, not a join onto data. It is the one decoration that
    # still works during an index outage.
    assert marks == {
        "benched": [],
        "deepened": 0,
        "scored": 0,
        "flagged": 0,
        "blend_wired": 1,
        # Added Aug 26 with the '26 projections: whether the points
        # column is reading forward or falling back to measured '25.
        "projected": False,
    }
    assert "const OUT_RED" not in out, "no frozen list survives an outage"
    assert _map(out, "FB_INJURIES") == {}
    assert "bases = { QB: 24.5" in out, "with no stats the points column is left alone"
