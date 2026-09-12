"""FFBets does not show hurt people (owner, Sep 12).

A touchdown prop on a man who will not play is a dead bet, not a weak one.
The row already carried "Sleeper flag: Out." underneath it -- true, labelled,
and still the wrong thing to leave on a board under a confidence bar. So the
lean comes off, and the caption says who came off and on whose say-so.

The pulled half is carried alongside the kept half all the way to the
injection for one reason: an empty board with a pull is a real measurement
and has to reach the page, while an empty board without one means the
curated parse found nothing and must leave the page's const alone. Collapsing
those two would serve the full curated table -- including the men just
pulled -- exactly when the pull mattered most.
"""

from __future__ import annotations

from pathlib import Path

from app.feeds import injury, vegas
from app.feeds import players as players_mod


def _index(flags: dict[str, str | None]):
    """A player index carrying one row per name, with the given flag.

    Keyed through the kernel's own `match_key`, like the real index: a
    hand-rolled .lower() here would pass while production missed.
    """
    players, by_name = {}, {}
    for i, (name, flag) in enumerate(flags.items(), start=1):
        players[str(i)] = {
            "id": str(i),
            "name": name,
            "position": "WR",
            "team": "SF",
            "injury_status": flag,
            "rank": i,
        }
        by_name[players_mod.match_key(name)] = str(i)
    return {"players": players, "by_name": by_name}


def _lean(name: str) -> dict:
    return {
        "name": name,
        "meta": "WR · SF",
        "prop": "Receiving TDs",
        "line": "0.5",
        "lean": "OVER",
        "conf": 60,
        "why": "curated.",
    }


def test_sidelined_names_the_out_tier_and_nothing_else():
    index = _index(
        {
            "Out Man": "Out",
            "Doubtful Man": "Doubtful",
            "Reserve Man": "IR",
            "Questionable Man": "Questionable",
            "Healthy Man": None,
        }
    )
    names = ("Out Man", "Doubtful Man", "Reserve Man", "Questionable Man", "Healthy Man")

    hurt = injury.sidelined(index, names)

    assert hurt == {"Out Man": "Out", "Doubtful Man": "Doubtful", "Reserve Man": "IR"}
    # Questionable plays most Sundays: his lean stands, wearing the flag
    # clause `lean_clauses` already writes.
    assert "Questionable Man" not in hurt
    assert "Healthy Man" not in hurt


def test_a_name_the_index_cannot_resolve_is_never_pulled():
    # Nothing said rather than something invented -- the same three-valued
    # honesty `live_status` keeps.
    assert injury.sidelined(_index({"Somebody Else": "Out"}), ("Unknown Man",)) == {}
    assert injury.sidelined(None, ("Unknown Man",)) == {}


def test_drop_sidelined_splits_the_board_and_leaves_the_rest_untouched():
    preds = [_lean("Out Man"), _lean("Healthy Man")]

    kept, pulled = vegas.drop_sidelined(preds, {"Out Man": "Out"})

    assert [row["name"] for row in kept] == ["Healthy Man"]
    assert pulled == [{"name": "Out Man", "flag": "Out"}]
    # The surviving row is the curated object itself, not a rebuild that
    # could quietly drop a clause another pass had appended.
    assert kept[0] is preds[1]


def test_no_flags_at_all_keeps_every_lean():
    preds = [_lean("A"), _lean("B")]
    for flags in ({}, None):
        kept, pulled = vegas.drop_sidelined(preds, flags)
        assert [row["name"] for row in kept] == ["A", "B"]
        assert pulled == []


def test_the_caption_names_who_was_pulled():
    caption = vegas.pulled_caption(
        [{"name": "Out Man", "flag": "Out"}, {"name": "Hurt Man", "flag": "Doubtful"}]
    )
    assert "Out Man (Out)" in caption
    assert "Hurt Man (Doubtful)" in caption
    assert "Sleeper" in caption  # whose say-so, not the app's own claim
    assert vegas.pulled_caption([]) == ""


def test_a_hurt_lean_leaves_the_served_board_and_the_caption_says_so():
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    preds = vegas.curated_predictions()
    assert any(p["name"] == "Puka Nacua" for p in preds)

    kept, pulled = vegas.drop_sidelined(preds, {"Puka Nacua": "Out"})
    served = vegas.inject_predictions(html, kept, pulled)

    const = served.split("const PREDICTIONS = ")[1].split("];")[0]
    assert "Puka Nacua" not in const
    assert "Josh Allen" in const
    assert "Puka Nacua (Out)" in served


def test_every_lean_pulled_still_reaches_the_page():
    # The verdict-wipe class: empty WITH a pull is a real answer. Serving
    # the curated const here would put every hurt player straight back.
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    preds = vegas.curated_predictions()
    flags = {p["name"]: "Out" for p in preds}

    kept, pulled = vegas.drop_sidelined(preds, flags)
    served = vegas.inject_predictions(html, kept, pulled)

    assert kept == []
    assert "const PREDICTIONS = [];" in served
    assert "Puka Nacua" not in served.split("const PREDICTIONS = ")[1].split("];")[0]


def test_empty_without_a_pull_still_leaves_the_page_alone():
    # A failed curated parse is not a measurement, and must not empty the
    # board -- the guard `inject_predictions` has always had.
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    assert vegas.inject_predictions(html, [], []) == html
    assert vegas.inject_predictions(html, []) == html


def test_the_served_board_drops_a_flagged_lean(tmp_path):
    """End to end through the composer, because the units passing proves
    only that the pieces work -- this proves `main` actually calls them,
    in the right order, after every clause pass has run."""
    import asyncio

    from fastapi.testclient import TestClient

    from app import main
    from app.feeds import projections
    from app.feeds.store import FileFeedStore
    from app.routes import feeds as feeds_route

    # Two curated leans, one man flagged Out and one clear.
    index = _index({"Puka Nacua": "Out", "Josh Allen": None})
    index["v"] = players_mod.INDEX_VERSION
    index["players"]["1"].update(position="WR", team="LAR")
    index["players"]["2"].update(position="QB", team="BUF")
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    asyncio.run(
        store.save(
            {
                "items": [],
                "week_projections": {
                    "v": projections.WEEK_REDUCE_VERSION,
                    "week": 1,
                    "companies": ["rotowire"],
                    "players": {},
                },
                "vegas": {
                    "fetched_at": "2026-09-12T12:00:00+00:00",
                    "week_label": "Week 1",
                    "games": [
                        {
                            "game": "LAR @ BUF",
                            "fav": "BUF -3.5",
                            "total": "48.5",
                            "kickoff": "2026-09-13T17:00Z",
                            "away_name": "Los Angeles Rams",
                            "home_name": "Buffalo Bills",
                            "tv": "CBS",
                            "imp": "",
                            "read": "",
                        }
                    ],
                },
            }
        )
    )
    asyncio.run(store.save_players(index))
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    main.app.dependency_overrides[feeds_route.get_optional_feed_store] = lambda: store
    try:
        served = TestClient(main.app).get("/app/").text
    finally:
        main.app.dependency_overrides.clear()

    board = served.split("const PREDICTIONS = ")[1].split("];")[0]
    assert "Puka Nacua" not in board  # flagged Out: pulled
    assert "Josh Allen" in board  # no flag: untouched
    assert "Puka Nacua (Out)" in served  # and the caption says so
    # The watchdog's own invariant: no out-tier flag clause survives on the
    # board, because the rows carrying one are gone.
    assert "Sleeper flag: Out." not in board
