"""Tests for poll() itself -- the failure isolation the sync depends on.

merge() is covered in test_feeds.py; this file is about what happens when
publishers misbehave, which they will.
"""

import httpx
import respx

from app.feeds import poller
from app.feeds.sources import Source

A = Source(
    key="a", name="Source A", url="https://a.example/rss", tier=1, budget_hours=24, attribution="A"
)
B = Source(
    key="b", name="Source B", url="https://b.example/rss", tier=2, budget_hours=48, attribution="B"
)

FEED = """<?xml version="1.0"?><rss><channel>
<item><title>Item one</title><link>https://a.example/1</link>
<pubDate>Fri, 14 Aug 2026 12:00:00 GMT</pubDate></item>
</channel></rss>"""


@respx.mock
async def test_one_failing_source_does_not_stop_the_others():
    """The whole point of isolating fetches: four good feeds still land when
    the fifth is down."""
    respx.get(A.url).mock(return_value=httpx.Response(200, text=FEED))
    respx.get(B.url).mock(return_value=httpx.Response(500, text="boom"))

    result = await poller.poll((A, B))

    assert len(result["items"]) == 1
    assert result["sources"]["a"]["ok"] is True
    assert result["sources"]["b"]["ok"] is False
    assert "500" in result["sources"]["b"]["error"]


@respx.mock
async def test_a_network_error_is_captured_not_raised():
    respx.get(A.url).mock(side_effect=httpx.ConnectError("dns is down"))

    result = await poller.poll((A,))

    assert result["items"] == []
    assert result["sources"]["a"]["ok"] is False
    assert "ConnectError" in result["sources"]["a"]["error"]


@respx.mock
async def test_a_timeout_is_captured_not_raised():
    respx.get(A.url).mock(side_effect=httpx.ReadTimeout("slow"))

    result = await poller.poll((A,))

    assert result["sources"]["a"]["ok"] is False
    assert "ReadTimeout" in result["sources"]["a"]["error"]


@respx.mock
async def test_a_200_that_is_not_a_feed_is_reported_not_silently_empty():
    """A publisher serving an HTML error page with status 200 must look like a
    failure, otherwise it is indistinguishable from a quiet news day."""
    respx.get(A.url).mock(return_value=httpx.Response(200, text="<html>oops</html>"))

    result = await poller.poll((A,))

    assert result["sources"]["a"]["ok"] is False
    assert result["sources"]["a"]["error"] == "parsed 0 items"


@respx.mock
async def test_every_source_failing_still_returns_a_well_formed_result():
    respx.get(A.url).mock(return_value=httpx.Response(503))
    respx.get(B.url).mock(return_value=httpx.Response(404))

    result = await poller.poll((A, B))

    assert result["items"] == []
    assert set(result["sources"]) == {"a", "b"}
    assert all(not s["ok"] for s in result["sources"].values())
    assert result["polled_at"]


@respx.mock
async def test_source_metadata_is_carried_through_for_the_ui():
    """Attribution and budget travel with the status so the UI can render
    the required credit and an honest freshness label."""
    respx.get(A.url).mock(return_value=httpx.Response(200, text=FEED))

    status = (await poller.poll((A,)))["sources"]["a"]

    assert status["name"] == "Source A"
    assert status["tier"] == 1
    assert status["attribution"] == "A"
    assert status["budget_hours"] == 24
    assert status["item_count"] == 1


@respx.mock
async def test_items_are_stamped_with_their_source():
    respx.get(A.url).mock(return_value=httpx.Response(200, text=FEED))

    item = (await poller.poll((A,)))["items"][0]

    assert item["source_key"] == "a"
    assert item["source_name"] == "Source A"
    assert item["tier"] == 1


@respx.mock
async def test_an_identifying_user_agent_is_sent():
    """Publishers block unidentified clients, and it is the polite thing."""
    route = respx.get(A.url).mock(return_value=httpx.Response(200, text=FEED))

    await poller.poll((A,))

    assert "FBBible" in route.calls[0].request.headers["user-agent"]


# --- last_ok_at survives a failed poll --------------------------------------
#
# Status is rebuilt wholesale every sync, so one transient refusal used to
# erase the fact that a publisher answered an hour ago -- and the watchdog
# treated that single miss as fatal (GAP_REVIEW: verify-live false-alarms
# on one transient error). The stamp is what lets a checker tell "missed
# one poll" from "silent past its own budget".


def test_a_successful_poll_stamps_its_own_fetch_time():
    status = {"a": {"ok": True, "fetched_at": "2026-08-29T10:00:00+00:00"}}

    out = poller.carry_last_ok(status, {"a": {"last_ok_at": "2026-08-29T02:00:00+00:00"}})

    assert out["a"]["last_ok_at"] == "2026-08-29T10:00:00+00:00"


def test_a_failed_poll_keeps_the_previous_success_stamp():
    status = {"a": {"ok": False, "fetched_at": "2026-08-29T10:00:00+00:00"}}

    out = poller.carry_last_ok(status, {"a": {"last_ok_at": "2026-08-29T09:00:00+00:00"}})

    assert out["a"]["last_ok_at"] == "2026-08-29T09:00:00+00:00"


def test_a_source_that_never_answered_says_so():
    """None, not a fabricated stamp -- a feed that has never once
    answered is a dead config, and the checker should see that."""
    status = {"a": {"ok": False}}

    assert poller.carry_last_ok(status, {})["a"]["last_ok_at"] is None
    assert poller.carry_last_ok({"a": {"ok": False}}, None)["a"]["last_ok_at"] is None


def test_the_stamp_survives_a_previous_blob_without_the_field():
    """Stored status from before this field existed carries no
    last_ok_at; the carry must degrade to None rather than KeyError."""
    status = {"a": {"ok": False, "fetched_at": "x"}}

    assert poller.carry_last_ok(status, {"a": {"ok": True}})["a"]["last_ok_at"] is None
