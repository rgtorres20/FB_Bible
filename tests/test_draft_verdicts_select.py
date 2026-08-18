"""Item selection for the hourly AI-drafting job.

The job gets one model request an hour; selection decides whether coverage
accumulates or the same newest items are re-drafted forever. Contract:
already-covered items are skipped, items about top-300 players go first,
wire order survives within each group, and the cap holds.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location("draft_verdicts", Path("scripts/draft_verdicts.py"))
draft_verdicts = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(draft_verdicts)


def _item(item_id: str, rank: int | None) -> dict:
    players = [{"id": "p" + item_id, "name": "N", "rank": rank}] if rank is not None else []
    return {"id": item_id, "title": item_id, "players": players}


def test_covered_items_are_skipped():
    items = [_item("a", 10), _item("b", 20)]
    assert draft_verdicts.select_items(items, {"a"}) == [_item("b", 20)]


def test_top300_items_go_first_and_order_survives():
    items = [_item("tail", 900), _item("unranked", None), _item("t1", 5), _item("t2", 299)]
    picked = draft_verdicts.select_items(items, set())
    assert [i["id"] for i in picked] == ["t1", "t2", "tail", "unranked"]


def test_cap_holds():
    items = [_item(str(i), 400) for i in range(40)]
    assert len(draft_verdicts.select_items(items, set())) == draft_verdicts.MAX_ITEMS


def test_nothing_pending_means_nothing_selected():
    items = [_item("a", 10)]
    assert draft_verdicts.select_items(items, {"a"}) == []
