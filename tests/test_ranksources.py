"""The Draft analyzer's source panel: what the average is made of.

Owner, Aug 21: the source list "should probably belong in the draft
analyzer so they know how the average is created", and they want to "see
live updates when one is added or removed".

So there are three things to hold down, and each has its own failure:

1. The payload reaches the page (`board.inject_sources`).
2. It stays current without a hard reload (`/app/data/ranksources.json`).
3. The panel actually renders — the failure this repo keeps paying for is
   a control wired to nothing, and `mobile.js` binds to a literal in a
   document the design project owns. That one runs the real script against
   the real anchors under node.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.feeds import board, page, ranklists
from app.feeds.store import FileFeedStore
from app.routes import access as access_route
from app.routes import feeds as feeds_route

JS_DIR = pathlib.Path("tests/js")
INDEX = pathlib.Path("frontend/index.html")
OWNER = "owner@example.com"
TODAY = date(2026, 8, 21)

# Real players off the app's own board.
PASTE = "1. Jahmyr Gibbs\n2. Bijan Robinson\n3. Puka Nacua"


def _lists():
    return [
        ranklists.RankList(
            key="sheet", name="Overall draft cheat sheet 2026", as_of=TODAY, order=("A", "B")
        ),
        ranklists.RankList(
            key="lb",
            name="ESPN IDP LB 2026",
            as_of=date(2026, 8, 1),
            order=("C",),
            active=False,
            scope="LB",
        ),
    ]


# --- 1. the payload reaches the page -----------------------------------


def test_the_payload_says_what_a_reader_needs_to_judge_a_list():
    """Size, date, age, scope and whether it counts. Nothing derived, so
    nothing here can be wrong in a way the reader cannot see."""
    got = ranklists.sources_payload(_lists(), TODAY)
    assert [s["name"] for s in got] == ["Overall draft cheat sheet 2026", "ESPN IDP LB 2026"]
    assert got[0] == {
        "key": "sheet",
        "name": "Overall draft cheat sheet 2026",
        "n": 2,
        "asOf": "2026-08-21",
        "age": 0,
        "scope": "OVERALL",
        "active": True,
    }
    assert got[1]["age"] == 20
    assert got[1]["scope"] == "LB"


def test_a_switched_off_list_is_reported_rather_than_hidden():
    """ "Why is this source not counting" is the question that started this
    thread, and a panel showing only the active lists cannot answer it."""
    got = ranklists.sources_payload(_lists(), TODAY)
    assert [s["active"] for s in got] == [True, False]
    assert len(got) == 2


def test_an_empty_list_does_not_claim_to_be_in_the_blend():
    """A list that parsed to nothing is stored active but contributes
    nothing — reporting it as active would be a false positive."""
    empty = ranklists.RankList(key="e", name="Empty", as_of=TODAY, order=())
    assert ranklists.sources_payload([empty], TODAY)[0]["active"] is False


def test_the_injection_fires_against_the_committed_page():
    """The anchor is `const RAW_BOARD = [`, which the design document owns.
    A resync that renames it must fail here, not silently drop the panel."""
    html = INDEX.read_text(encoding="utf-8")
    out, n = board.inject_sources(html, ranklists.sources_payload(_lists(), TODAY))
    assert n == 2
    assert "const FB_RANK_SOURCES = " in out
    # Declared before the board it describes, and only once.
    assert out.count("const FB_RANK_SOURCES") == 1
    assert out.index("FB_RANK_SOURCES") < out.index("const RAW_BOARD = [")


def test_the_injection_misses_cleanly_rather_than_half_firing():
    out, n = board.inject_sources("<html>no board here</html>", [{"key": "x"}])
    assert n == 0
    assert out == "<html>no board here</html>"


def test_the_served_page_carries_the_committed_lists():
    """End to end, no store and signed out: the panel is right even when
    every live feed is down, because these lists are committed data."""
    served = TestClient(main.app).get("/app/").text
    assert "const FB_RANK_SOURCES = " in served
    payload = json.loads(re.search(r"const FB_RANK_SOURCES = (\[.*?\]);\n", served, re.S).group(1))
    assert len(payload) == len(ranklists.builtins()) == 5
    assert sum(1 for s in payload if s["active"]) == 2


# --- 2. it stays current ------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    s = get_settings()
    monkeypatch.setattr(s, "app_auth", True, raising=False)
    monkeypatch.setattr(s, "owner_email", OWNER, raising=False)
    monkeypatch.setattr(s, "app_owner_code", "open-sesame", raising=False)
    monkeypatch.setattr(s, "session_secret", "unit-test-secret", raising=False)
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    main.app.dependency_overrides[feeds_route.get_optional_feed_store] = lambda: store
    monkeypatch.setattr(access_route, "build_feed_store", lambda _s: store)
    c = TestClient(main.app)
    c.post("/login", data={"email": OWNER, "code": "open-sesame"})
    yield c
    main.app.dependency_overrides.clear()


def _names(client):
    return [s["name"] for s in client.get("/app/data/ranksources.json").json()]


def _save(client, name, text):
    client.post(
        "/app/mine/list",
        data={"name": name, "text": text, "as_of": ""},
        files={"file": ("", b"", "text/plain")},
        follow_redirects=False,
    )


def test_adding_a_list_shows_up_without_a_reload(client):
    """The owner's actual ask. A list is added at /app/mine, which is a
    different tab; the analyzer re-reads this endpoint on focus, so the
    change has to be visible here immediately."""
    before = _names(client)
    assert "My own board" not in before
    _save(client, "My own board", PASTE)
    assert "My own board" in _names(client)
    assert len(_names(client)) == len(before) + 1


def test_removing_a_list_takes_it_off_the_panel(client):
    _save(client, "My own board", PASTE)
    client.post("/app/mine/list/delete", data={"key": "my own board"}, follow_redirects=False)
    assert "My own board" not in _names(client)


def test_switching_a_list_off_keeps_it_on_the_panel_marked_off(client):
    """Off is not gone. The panel exists to explain the average, and a
    list the owner deliberately parked is part of that explanation."""
    _save(client, "My own board", PASTE)
    client.post("/app/mine/list/toggle", data={"key": "my own board"}, follow_redirects=False)
    panel = client.get("/app/data/ranksources.json").json()
    mine = [s for s in panel if s["key"] == "my own board"]
    assert len(mine) == 1
    assert mine[0]["active"] is False


def test_the_panel_holds_only_this_users_lists(client):
    """A saved list is per-email in the store, so the endpoint must join
    the committed set to *this* session's lists and nobody else's."""
    _save(client, "Private board", PASTE)
    payload = client.get("/app/data/ranksources.json").json()
    assert [s["name"] for s in payload if s["key"] == "private board"] == ["Private board"]
    plain = ranklists.sources_payload(ranklists.builtins(), date.today())
    assert "private board" not in {s["key"] for s in plain}


def test_the_gate_covers_the_panel_like_every_other_app_path(client):
    """With the login gate on, this is user data. It reads a signed-in
    user's own lists, so it must not answer an unauthenticated caller."""
    resp = TestClient(main.app).get("/app/data/ranksources.json")
    assert resp.status_code == 401


def test_with_the_gate_off_a_visitor_gets_the_committed_set():
    """Default posture — no login required. The committed lists are real
    and are what the blend is using, so an error would be a worse answer
    than the truth."""
    resp = TestClient(main.app).get("/app/data/ranksources.json")
    assert resp.status_code == 200
    assert len(resp.json()) == 5
    assert all(s["scope"] in ("OVERALL", "DL", "LB", "DB") for s in resp.json())


# --- 3. the panel renders -----------------------------------------------


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    """Run the real mobile.js against the real anchors from the committed
    index.html. Not a fixture page: the whole risk being covered is that
    the design document stops carrying the row the panel hangs off."""
    if shutil.which("node") is None:  # pragma: no cover - CI pins node
        pytest.fail("node is required: this test is the only proof the panel renders")
    # The SERVED page, not the committed one. mobile.js runs in a browser
    # against what the server sent, and the server renames the row this
    # panel hangs off (page.source_truth). Reading the file would test an
    # anchor no browser ever sees.
    html, misses = page.apply(INDEX.read_text(encoding="utf-8"), page.PRE)
    assert not misses, f"serve-time transforms found no anchor for {misses}"
    # Every styled span and div from the served document, with its real
    # text. Both decorators match on style and read textContent, so this
    # is the same haystack the browser gives them.
    anchors = [
        {
            "tag": m.group(1),
            "style": m.group(2),
            "text": re.sub(r"<[^>]+>", "", m.group(3)).strip(),
        }
        for m in re.finditer(r"<(span|div) style=\"([^\"]*)\"[^>]*>([^<]*)</\1>", html)
    ]
    work = tmp_path_factory.mktemp("sources")
    fixture = work / "fixture.json"
    fixture.write_text(
        json.dumps({"anchors": anchors, "sources": ranklists.sources_payload(_lists(), TODAY)}),
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["node", str(JS_DIR / "sources_harness.js"), str(fixture)],
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
    """It hangs off the analyzer's "Board order" row — a serve-time
    rename, so this also fails if that transform stops firing."""
    assert rendered["rendered"], (
        "mobile.js found no anchor in the served page — the "
        '"Board order" row it binds to has moved or been renamed'
    )


def test_it_names_every_list_and_says_which_ones_count(rendered):
    nodes = _flat(rendered["panel"])
    names = [n["text"] for n in nodes if n["cls"] == "fb-src-name"]
    states = [n["text"] for n in nodes if n["cls"] == "fb-src-state"]
    assert names == ["Overall draft cheat sheet 2026", "ESPN IDP LB 2026"]
    assert states == ["in the average", "off"]


def test_it_states_the_size_the_date_and_the_age_of_each_list(rendered):
    """Owner: "these can get outdated once season starts." An age nobody
    can see is an age nobody acts on."""
    meta = [n["text"] for n in _flat(rendered["panel"]) if n["cls"] == "fb-src-meta"]
    assert meta[0] == "2 players · as of 2026-08-21 · today"
    assert meta[1] == "1 players · as of 2026-08-01 · 20 days old · ranks within LB"


def test_it_explains_the_average_without_mentioning_weights(rendered):
    """There are none. The panel describing a share or a weight would be
    describing code that was deleted."""
    note = next(n["text"] for n in _flat(rendered["panel"]) if n["cls"] == "fb-src-note")
    assert "counts the same" in note
    assert "average place across the lists that carry him" in note
    assert "weight" not in note.lower()


def test_it_counts_the_lists_actually_in_the_blend(rendered):
    head = next(n["text"] for n in _flat(rendered["panel"]) if n["cls"] == "fb-src-head")
    assert head == "How the average is made · 1 of 2 lists in the blend"


def test_it_offers_the_way_to_change_the_set(rendered):
    """A panel that explains the average and leaves no way to change it
    sends the reader hunting through the settings screen."""
    foot = next(n for n in _flat(rendered["panel"]) if n["cls"] == "fb-src-foot")
    assert foot["href"] == "/app/mine"


# --- the draft-tool links hang off the same document --------------------
# Not new work: `linkDraftTools` has bound to the "My team" header since
# Aug 20 with nothing checking it. The harness runs the whole decorator,
# so covering it costs one test and closes a real gap.


def test_the_draft_tool_links_render(rendered):
    """Links into the mock room, league settings, Next man up, the
    scorecard and the scoring board. They hang off the analyzer's "My
    team" header, which the design project owns."""
    ids = [x["id"] for x in rendered["links"]]
    assert set(ids) == {
        "fb-mock-link",
        "fb-leagues-link",
        "fb-nextup-link",
        "fb-score-link",
        "fb-scoring-link",
    }


def test_the_draft_tool_links_open_outside_the_shell(rendered):
    """Installed as a PWA there is no back button, so in-shell navigation
    strands the user — the failure that started the navigation work."""
    for link in rendered["links"]:
        assert link["target"] == "_blank", link["id"]
        assert link["href"].startswith("/app/"), link["id"]
