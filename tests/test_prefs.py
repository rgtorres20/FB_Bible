"""A list you cannot save is not a list.

Owner, Aug 26: *"i see that back up running backs list does not save for
users why make a list you cant save"*, and the general form of the same
defect: *"when i log into other devices i dont see my changes"*.

The design document keeps fourteen things in localStorage. The ones that
are the reader's own work — the order they put the backup running backs
in, the rows they cleared, their queue, who they marked taken — were
therefore pinned to one browser.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.feeds import page, prefs

INDEX = Path("frontend/index.html")


# --- which keys follow the account ----------------------------------------


def test_the_backup_running_backs_list_is_one_of_them():
    """The reported one. Its order and its cleared rows are two keys and
    both have to travel, or reordering follows you and clearing does not."""
    assert "ww_cuff_order" in prefs.MANAGED
    assert "ww_cuff_hidden" in prefs.MANAGED


def test_appearance_stays_on_the_device():
    """A phone in the dark and a desk monitor are different rooms. These
    are also pinned as immutable storage keys in CLAUDE.md."""
    for key in ("ww_theme", "ww_skin", "fb_team"):
        assert key not in prefs.MANAGED, key


def test_the_sleepers_list_is_not_managed_here():
    """It has its own route and its own store. Two writers for one list
    is how the two of them start disagreeing."""
    assert "ww_my_sleepers" not in prefs.MANAGED


def test_a_cache_is_not_somebody_s_work():
    assert "ww_live" not in prefs.MANAGED
    assert "ww_api_base" not in prefs.MANAGED


# --- saving ---------------------------------------------------------------


def test_a_write_merges_rather_than_replaces():
    """Two tabs are two writers. A replace would let the draft board on a
    laptop delete what the cuffs tab on a phone just saved."""
    saved = {prefs.KEY: {"ww_queue": "[1]", "ww_taken": "[2]"}}

    merged = prefs.merge(saved, {"ww_queue": "[9]"})

    assert merged == {"ww_queue": "[9]", "ww_taken": "[2]"}


def test_an_unmanaged_key_is_refused():
    """The endpoint takes whatever the page sends. It must not become a
    general-purpose key-value store for anyone with an account."""
    assert prefs.merge({}, {"ww_theme": "dark", "evil": "x"}) == {}


def test_a_non_string_value_is_refused():
    assert prefs.merge({}, {"ww_queue": ["not", "a", "string"]}) == {}


def test_an_oversized_value_is_dropped_not_truncated():
    """Half a JSON array is not a smaller list, it is a corrupt one — the
    page would read it back as empty and lose the lot."""
    huge = "x" * (prefs.MAX_VALUE + 1)

    assert prefs.merge({}, {"ww_queue": huge}) == {}


def test_a_retired_key_stops_being_replayed():
    """Filtered on the way out as well as in, so shrinking MANAGED drops
    the key from the page instead of serving it forever."""
    saved = {prefs.KEY: {"ww_queue": "[1]", "ww_retired_thing": "[2]"}}

    assert prefs.stored(saved) == {"ww_queue": "[1]"}


def test_a_blob_over_the_cap_loses_the_fewest_lists():
    """Nothing here is older or less wanted than anything else, so the
    eviction keeps the smallest values — dropping one big list rather
    than several small ones."""
    # Built the only way it can really happen: one accepted value at a
    # time, each inside MAX_VALUE, until the total goes over.
    saved: dict = {}
    for key in ("ww_taken", "ww_queue", "ww_my_teams", "ww_scout_dismissed"):
        saved = {prefs.KEY: prefs.merge(saved, {key: "y" * (prefs.MAX_VALUE - 1)})}

    merged = prefs.merge(saved, {"ww_cuff_order": "[3,1,2]"})

    total = sum(len(k) + len(v) for k, v in merged.items())
    assert total <= prefs.MAX_TOTAL
    # The small one it was just handed survives; a big one was dropped.
    assert merged["ww_cuff_order"] == "[3,1,2]"
    assert sum(1 for v in merged.values() if len(v) > 1000) < 4


# --- the shim -------------------------------------------------------------


def _served(saved):
    html, misses = page.apply(INDEX.read_text(encoding="utf-8"), page.PRE)
    assert not misses
    out, missed = page.prefs_shim(html, saved)
    assert not missed
    return out


def test_the_shim_lands_before_the_page_reads_those_keys():
    """The component reads them as it boots. A shim installed after that
    has already missed the only read that decides the first screen."""
    served = _served({"ww_cuff_order": "[3,1,2]"})

    assert served.index("localStorage.getItem = function") < served.index("</head>")


def test_the_account_s_copy_reaches_the_page():
    served = _served({"ww_cuff_order": "[3,1,2]"})

    assert '"ww_cuff_order":"[3,1,2]"' in served


def test_a_signed_out_reader_is_left_completely_alone():
    """No account means no list to follow them. That is the correct mode,
    not a degraded one."""
    html, _ = page.apply(INDEX.read_text(encoding="utf-8"), page.PRE)
    out, misses = page.prefs_shim(html, None)

    assert (out, misses) == (html, [])


def test_an_unmanaged_key_passes_straight_through_to_the_browser():
    """A theme, a cache or a dev override has to behave exactly as before.
    This shim redirects nine keys, not localStorage itself."""
    served = _served({})
    shim = re.search(r"<script>\(function\(\)\{.*?\}\)\(\);</script>", served, re.S).group(0)

    assert "if (!managed(k)) return real.setItem(k, v);" in shim
    assert "if (!managed(k)) return real.removeItem(k);" in shim


def test_a_value_containing_a_script_tag_cannot_end_the_element():
    """Player names come from Sleeper and list names are typed by people
    at /app/mine, so this is reachable, not theoretical."""
    served = _served({"ww_queue": '["</script><img src=x>"]'})

    assert "</script><img" not in served
    assert "<\\/script>" in served


def test_the_shim_is_valid_javascript(tmp_path):
    """It is assembled by string formatting in Python, which no linter
    here reads as code. Parsed by node instead of hoped about."""
    import shutil
    import subprocess

    if shutil.which("node") is None:  # pragma: no cover - CI pins node
        raise AssertionError("node is required to parse the injected shim")
    served = _served({"ww_cuff_order": "[3,1,2]"})
    shim = re.search(r"<script>(\(function\(\)\{.*?\}\)\(\);)</script>", served, re.S).group(1)
    script = tmp_path / "shim.js"
    script.write_text(shim, encoding="utf-8")

    proc = subprocess.run(["node", "--check", str(script)], capture_output=True, text=True)

    assert proc.returncode == 0, proc.stderr


def test_the_managed_list_the_page_sees_is_the_one_python_holds():
    """Two copies of this list is how the shim starts redirecting a key
    the server then refuses to store."""
    served = _served({})
    shipped = re.search(r"MANAGED = (\[[^\]]*\])", served).group(1)

    assert json.loads(shipped) == list(prefs.MANAGED)


# --- the route ------------------------------------------------------------

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.feeds.store import FileFeedStore  # noqa: E402
from app.routes import access as access_route  # noqa: E402
from app.routes import feeds as feeds_route  # noqa: E402

OWNER = "owner@example.com"


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
    c._store = store  # type: ignore[attr-defined]
    yield c
    main.app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_a_reordered_backup_list_survives_a_new_device(client, anyio_backend):
    """The whole complaint, end to end: save from one browser, and the
    next page render on any other one is served the same order."""
    client.post("/app/mine/prefs", json={"ww_cuff_order": "[3,1,2]"})

    data = await client._store.load_user(OWNER)
    assert prefs.stored(data) == {"ww_cuff_order": "[3,1,2]"}

    served = client.get("/app/").text
    assert '"ww_cuff_order":"[3,1,2]"' in served


@pytest.mark.anyio
async def test_two_tabs_do_not_delete_each_other_s_work(client, anyio_backend):
    """A replace instead of a merge would make the second writer win the
    whole blob rather than its own key."""
    client.post("/app/mine/prefs", json={"ww_queue": "[1]"})
    client.post("/app/mine/prefs", json={"ww_cuff_hidden": '["Tank Bigsby"]'})

    data = await client._store.load_user(OWNER)
    assert prefs.stored(data) == {"ww_queue": "[1]", "ww_cuff_hidden": '["Tank Bigsby"]'}


def test_a_stranger_cannot_save(client):
    """401, not a redirect: the shim calls this with fetch, and a 303 to
    /login would be followed silently and stored as if it were data."""
    fresh = TestClient(main.app)

    assert fresh.post("/app/mine/prefs", json={"ww_queue": "[1]"}).status_code == 401


def test_a_malformed_body_is_a_400_not_a_500(client):
    assert client.post("/app/mine/prefs", content=b"not json").status_code == 400
    assert client.post("/app/mine/prefs", json=["a", "list"]).status_code == 400
