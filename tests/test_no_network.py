"""The fence that keeps the suite off the network.

CLAUDE.md requires the tests to pass with no network. They always did --
by *attempting* a call and passing on the failure, which is a different
thing. The cost showed up as runtime: the suite swung between 11s and 65s
run to run, entirely on how fast the outbound proxy said no, and that made
a real regression impossible to see in a timing.

`tests/conftest.py` now blocks outbound sockets. This file is the fence's
own fence: a guard nobody checks stops guarding, quietly, the first time
somebody changes how the client connects.
"""

from __future__ import annotations

import socket
import urllib.request

import httpx
import pytest


def test_a_plain_socket_cannot_reach_out():
    with pytest.raises(OSError, match="blocked by the test fence"):
        socket.socket().connect(("example.com", 80))


def test_create_connection_cannot_reach_out():
    """urllib goes this way, which is how the mailer sends."""
    with pytest.raises(OSError, match="blocked by the test fence"):
        socket.create_connection(("example.com", 80))


def test_urllib_cannot_reach_out():
    with pytest.raises(OSError):
        urllib.request.urlopen("http://example.com/", timeout=5)


@pytest.mark.anyio
async def test_an_httpx_client_cannot_reach_out(anyio_backend):
    """The one that matters: every feed fetch in the app is an
    httpx.AsyncClient, so this is the call the fence exists to stop."""
    async with httpx.AsyncClient(timeout=5) as client:
        with pytest.raises(httpx.ConnectError):
            await client.get("https://api.sleeper.app/v1/players/nfl")


@pytest.mark.anyio
async def test_a_mocked_transport_still_works(anyio_backend):
    """The fence must not break the way the suite fakes HTTP. Nothing that
    fakes a response opens a socket, which is exactly why the block sits at
    the socket and not at the httpx transport -- respx and MockTransport
    both patch the transport, and a fence there would fight them."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        resp = await client.get("https://api.sleeper.app/v1/players/nfl")
    assert resp.json() == {"ok": True}


@pytest.mark.anyio
async def test_the_app_own_fetches_fail_fast_rather_than_hanging(anyio_backend):
    """The symptom this fixes. Unpatched, these reached the proxy and took
    seconds to be refused; they must now fail immediately and locally."""
    from app.feeds import players, stats

    for fetch in (players.fetch_index, stats.fetch):
        with pytest.raises(httpx.ConnectError):
            await fetch()
