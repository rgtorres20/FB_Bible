"""The sleepers list is the owner's, and its thread is the real wire.

Owner, Aug 25: "maybe the sleepers need a list of people that i can add
but we also show sleepers alerts in seperate thread where we search for
new articles on sleepers for ppr leagues" -- and plainly, "right now it
doesnt make sense and this list should be editble".

The tab was 19 rows transcribed by hand from PFF, Yahoo and Bleacher
Report on Aug 14 and frozen there: somebody else's picks, from before the
preseason, with no way to change them.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

from app.feeds import page, players, watchlist

JS_DIR = pathlib.Path("tests/js")
INDEX = pathlib.Path("frontend/index.html")


def _index(*names):
    """Built by the REAL builder, not hand-shaped.

    The hand-shaped version keyed `by_name` to player dicts carrying a
    `meta` field. The real index keys it to bare id strings and carries
    no `meta` at all. Both mistakes came from a docstring that said
    "player_dict", and a sibling module shipped the same read and raised
    AttributeError on the live page (Aug 26). A fixture that disagrees
    with its producer proves nothing, so this one goes through
    `build_index`.
    """
    return players.build_index(
        {
            str(i): {
                "active": True,
                "full_name": n,
                "position": "RB",
                "team": "LAR",
                "search_rank": i + 1,
            }
            for i, n in enumerate(names)
        }
    )


def _item(pid, title, published, source="PFF"):
    return {
        "title": title,
        "url": f"https://x/{title}",
        "source": source,
        "published": published,
        "players": [{"id": pid}],
    }


# --- the list is editable, which is the whole complaint ---------------------


def test_a_player_can_be_added_and_dropped():
    after_add = watchlist.add({}, "Blake Corum")
    assert after_add == ["Blake Corum"]

    assert watchlist.remove({watchlist.KEY: after_add}, "Blake Corum") == []


def test_order_is_the_order_they_were_added():
    """Not re-sorted. It is a list somebody is building, and the order
    they built it in is information."""
    stored: dict = {}
    for name in ("Blake Corum", "Jaylen Warren", "Tucker Kraft"):
        stored = {watchlist.KEY: watchlist.add(stored, name)}

    assert stored[watchlist.KEY] == ["Blake Corum", "Jaylen Warren", "Tucker Kraft"]


def test_the_same_player_twice_is_one_entry():
    """Deduped on match_key, the fold the boards already join by, so a
    curly apostrophe cannot make two rows that each catch half the wire."""
    once = watchlist.add({}, "De'Von Achane")

    assert watchlist.add({watchlist.KEY: once}, "De’Von Achane") == once
    assert watchlist.add({watchlist.KEY: once}, "de'von achane") == once


def test_dropping_is_spelling_insensitive_too():
    stored = {watchlist.KEY: ["De'Von Achane"]}

    assert watchlist.remove(stored, "De’Von Achane") == []


def test_a_blank_name_is_not_a_player():
    assert watchlist.add({}, "   ") == []
    assert watchlist.add({}, "") == []


def test_the_list_has_a_ceiling():
    """A paste of a whole cheat sheet must not turn a watchlist into a
    second ranking list -- there is already a place for those."""
    stored: dict = {}
    for i in range(watchlist.MAX_WATCHED + 10):
        stored = {watchlist.KEY: watchlist.add(stored, f"Player {i}")}

    assert len(stored[watchlist.KEY]) == watchlist.MAX_WATCHED


def test_junk_in_the_store_reads_as_an_empty_list():
    for junk in ({watchlist.KEY: "nope"}, {watchlist.KEY: [1, 2]}, {}, None):
        assert watchlist.watched(junk) == []


# --- the thread is a join, not a search -------------------------------------


def test_the_thread_returns_real_items_newest_first():
    idx = _index("Blake Corum")
    items = [
        _item("0", "older", "2026-08-20"),
        _item("0", "newer", "2026-08-24"),
    ]

    posts = watchlist.thread(idx, items, ["Blake Corum"])

    assert [p["title"] for p in posts] == ["newer", "older"]
    assert posts[0]["url"] and posts[0]["source"] == "PFF"


def test_a_player_written_about_three_times_appears_three_times():
    """A thread, not one-per-player. Three posts in a week IS the signal;
    collapsing them to one would throw away the thing being asked about."""
    idx = _index("Blake Corum")
    items = [_item("0", f"post {i}", f"2026-08-2{i}") for i in (1, 2, 3)]

    assert len(watchlist.thread(idx, items, ["Blake Corum"])) == 3


def test_items_about_nobody_watched_are_not_in_the_thread():
    idx = _index("Blake Corum")
    items = [_item("0", "mine", "2026-08-24"), _item("99", "someone else", "2026-08-25")]

    assert [p["title"] for p in watchlist.thread(idx, items, ["Blake Corum"])] == ["mine"]


def test_an_item_naming_two_watched_players_says_both():
    idx = _index("Blake Corum", "Jaylen Warren")
    item = {**_item("0", "both", "2026-08-24"), "players": [{"id": "0"}, {"id": "1"}]}

    posts = watchlist.thread(idx, [item], ["Blake Corum", "Jaylen Warren"])

    assert posts[0]["about"] == ["Blake Corum", "Jaylen Warren"]


# --- the honesty rules ------------------------------------------------------


def test_a_watched_player_with_no_coverage_reports_zero():
    """Never hidden. "Nobody is writing about him" is a real answer to
    the question a sleeper list asks -- often the point of one."""
    idx = _index("Blake Corum")

    out = watchlist.summary(idx, [], ["Blake Corum"])

    assert out["watched"] == [
        {"name": "Blake Corum", "posts": 0, "known": True, "meta": "RB · LAR"}
    ]
    assert out["posts"] == []


def test_a_name_the_index_does_not_know_stays_and_says_so():
    """Dropping it silently would be the app overruling what somebody
    typed. It stays on the list, flagged, so the reader knows WHY it will
    never collect wire rather than wondering."""
    out = watchlist.summary(_index(), [], ["Somebody Unrecognised"])

    assert out["watched"][0]["name"] == "Somebody Unrecognised"
    assert out["watched"][0]["known"] is False


def test_an_empty_list_is_an_empty_thread_not_everything():
    """The failure that would matter: no filter meaning no filtering, so
    an empty watchlist floods the tab with the entire wire."""
    idx = _index("Blake Corum")
    items = [_item("0", "anything", "2026-08-24")]

    assert watchlist.thread(idx, items, []) == []
    assert watchlist.summary(idx, items, [])["posts"] == []


# --- the panel actually renders --------------------------------------------
#
# The failure this repo keeps paying for is a control wired to nothing.
# `mobile.js` binds to an anchor a serve-time transform puts into a
# document the design project owns, so the only proof the tab has a list
# on it is running the real script against the real served page.


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    if shutil.which("node") is None:  # pragma: no cover - CI pins node
        pytest.fail("node is required: this test is the only proof the panel renders")
    # The SERVED page, not the committed one: the anchor does not exist on
    # disk, `page.sleepers_watchlist` puts it there. Reading the file would
    # test an anchor no browser ever sees.
    served, misses = page.apply(INDEX.read_text(encoding="utf-8"), page.PRE)
    assert not misses, f"serve-time transforms found no anchor for {misses}"

    payload = watchlist.summary(
        _index("Blake Corum", "Jaylen Warren"),
        [_item("0", "Corum pushing for a bigger share", "2026-08-25T12:00:00Z")],
        ["Blake Corum", "Jaylen Warren", "Nobody Atall"],
    )
    work = tmp_path_factory.mktemp("sleepers")
    fixture = work / "fixture.json"
    fixture.write_text(
        json.dumps({"hasAnchor": "data-fb-sleepers" in served, "payload": payload}),
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["node", str(JS_DIR / "sleepers_harness.js"), str(fixture)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _flat(node):
    out = [node]
    for kid in node["kids"]:
        out.extend(_flat(kid))
    return out


def test_the_panel_renders_at_all(rendered):
    """It hangs off an anchor the server inserts, so this fails if either
    the transform stops firing or mobile.js stops looking."""
    assert rendered["rendered"], (
        "mobile.js found no [data-fb-sleepers] in the served page — the "
        "transform that inserts it has stopped firing"
    )
    assert "/app/data/sleepers.json" in rendered["requested"]


def test_your_list_sits_above_the_analysts_table(rendered):
    """The owner's complaint was that the tab opened on somebody else's
    picks. Order is the fix, so order is asserted."""
    assert rendered["beforeAnchor"]


def test_it_offers_a_box_to_add_a_player(rendered):
    """ "this list should be editble" — the one thing the frozen table
    could not do."""
    boxes = [n for n in _flat(rendered["panel"]) if n["tag"] == "input"]
    assert [b["placeholder"] for b in boxes] == ["Add a player by name"]


def test_every_watched_player_has_a_remove(rendered):
    buttons = [n["text"] for n in _flat(rendered["panel"]) if "fb-src-btn" in n["cls"]]
    assert buttons == ["Add", "Remove", "Remove", "Remove"]


def test_a_player_nobody_has_written_about_says_so(rendered):
    """Rather than being hidden. "Nobody is talking about him" is a real
    answer to what a sleeper list asks, and often the point of one."""
    meta = [n["text"] for n in _flat(rendered["panel"]) if n["cls"] == "fb-src-meta"]
    assert meta[0] == "RB · LAR · 1 post"
    assert meta[1] == "RB · LAR · no posts yet"
    assert "no wire will match it" in meta[2]


def test_the_thread_links_the_real_article(rendered):
    """A join, not a summary: the row carries the item's own headline and
    its own link, so nothing here is the app's writing."""
    posts = [n for n in _flat(rendered["panel"]) if n["cls"] == "fb-sl-title"]
    assert [p["text"] for p in posts] == ["Corum pushing for a bigger share"]
    assert posts[0]["href"].startswith("https://x/")
