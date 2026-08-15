"""Poller fetch dispatch and the six-source sync, end to end over fake HTTP.

The queue-level contract: the rotoworld source routes to the page parser and
everything else to RSS, one broken publisher degrades that source only, and
a full poll of the real source list produces the per-source status the
freshness labels and the watchdog depend on.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from app.feeds import poller
from app.feeds.sources import FEED_SOURCES

ROTOWORLD_HTML = Path("tests/fixtures/rotoworld_sample.html").read_text(encoding="utf-8")

RSS2 = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>t</title>
<item><title>Headline one</title><link>https://x.example/1</link>
<pubDate>Fri, 14 Aug 2026 12:00:00 GMT</pubDate></item>
</channel></rss>"""


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _source(key: str):
    return next(s for s in FEED_SOURCES if s.key == key)


def _rss_source():
    return next(s for s in FEED_SOURCES if s.parser != "rotoworld")


# --- _fetch dispatch -------------------------------------------------------


async def test_fetch_routes_rotoworld_to_page_parser():
    async with _client(lambda req: httpx.Response(200, text=ROTOWORLD_HTML)) as client:
        source, items, error = await poller._fetch(client, _source("rotoworld_pn"))
    assert error is None
    assert items and all(i["source_key"] == "rotoworld_pn" for i in items)
    # Structural player fields survive dispatch -- this is the whole reason
    # the source has its own parser.
    assert any(i["players"] for i in items)


async def test_fetch_routes_rss_sources_to_rss_parser():
    async with _client(lambda req: httpx.Response(200, text=RSS2)) as client:
        source, items, error = await poller._fetch(client, _rss_source())
    assert error is None
    entries = [i.to_dict() if not isinstance(i, dict) else i for i in items]
    assert entries[0]["title"] == "Headline one"
    assert entries[0]["source_key"] == source.key


async def test_fetch_reports_http_status_as_error():
    async with _client(lambda req: httpx.Response(503)) as client:
        _, items, error = await poller._fetch(client, _rss_source())
    assert items == []
    assert error == "HTTP 503"


async def test_fetch_reports_zero_parses_as_error():
    async with _client(lambda req: httpx.Response(200, text="<html>no posts</html>")) as client:
        _, _, roto_err = await poller._fetch(client, _source("rotoworld_pn"))
    assert roto_err == "parsed 0 posts"
    empty_rss = "<?xml version='1.0'?><rss version='2.0'><channel></channel></rss>"
    async with _client(lambda req: httpx.Response(200, text=empty_rss)) as client:
        _, _, rss_err = await poller._fetch(client, _rss_source())
    assert rss_err == "parsed 0 items"


async def test_fetch_swallows_transport_exceptions():
    def boom(req):
        raise httpx.ConnectError("dns exploded")

    async with _client(boom) as client:
        _, items, error = await poller._fetch(client, _rss_source())
    assert items == []
    assert "ConnectError" in error


# --- poll: all six real sources over fake HTTP -----------------------------


def _route_all(broken_key: str | None = None):
    by_url = {s.url: s for s in FEED_SOURCES}

    def handler(request: httpx.Request) -> httpx.Response:
        source = by_url[str(request.url)]
        if source.key == broken_key:
            return httpx.Response(500)
        if source.parser == "rotoworld":
            return httpx.Response(200, text=ROTOWORLD_HTML)
        return httpx.Response(200, text=RSS2)

    return handler


async def test_poll_six_sources_end_to_end(monkeypatch):
    transport = httpx.MockTransport(_route_all())
    real_client = httpx.AsyncClient
    monkeypatch.setattr(poller.httpx, "AsyncClient", lambda **kw: real_client(transport=transport))
    result = await poller.poll()

    assert set(result["sources"]) == {s.key for s in FEED_SOURCES}
    assert len(result["sources"]) >= 6
    for key, status in result["sources"].items():
        assert status["ok"], f"{key}: {status['error']}"
        assert status["item_count"] > 0
    assert result["polled_at"]
    # Items are plain dicts by the time they leave poll() -- the store and
    # tagger both rely on that.
    assert all(isinstance(i, dict) for i in result["items"])


async def test_poll_one_broken_source_degrades_only_itself(monkeypatch):
    broken = _rss_source().key
    transport = httpx.MockTransport(_route_all(broken_key=broken))
    real_client = httpx.AsyncClient
    monkeypatch.setattr(poller.httpx, "AsyncClient", lambda **kw: real_client(transport=transport))
    result = await poller.poll()

    assert result["sources"][broken]["ok"] is False
    assert result["sources"][broken]["error"] == "HTTP 500"
    healthy = [k for k, v in result["sources"].items() if k != broken]
    assert healthy and all(result["sources"][k]["ok"] for k in healthy)
