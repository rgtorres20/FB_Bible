"""Retry policy for the verdict drafter.

The first live run against Google AI Studio returned HTTP 503 "model
overloaded" -- a busy free tier, not a broken one. A single attempt an hour
loses the whole hour to that, while retrying a permanently dead endpoint is
just a slower way to be wrong. The split between those two is the contract
here, and it is the same distinction that let a retired provider look
healthy for a day.
"""

from __future__ import annotations

import urllib.error

import pytest

from scripts import draft_verdicts as dv


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x", code, "boom", {}, None)


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch):
    monkeypatch.setattr(dv.time, "sleep", lambda _s: None)


def test_a_busy_provider_is_retried_and_can_succeed(monkeypatch):
    calls = {"n": 0}

    def flaky(items, key):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _http_error(503)
        return {"id-1": "a verdict"}

    monkeypatch.setattr(dv, "draft", flaky)
    assert dv.draft_with_retry([], "k") == {"id-1": "a verdict"}
    assert calls["n"] == 3


def test_retries_are_bounded_and_the_last_failure_surfaces(monkeypatch):
    calls = {"n": 0}

    def always_busy(items, key):
        calls["n"] += 1
        raise _http_error(503)

    monkeypatch.setattr(dv, "draft", always_busy)
    with pytest.raises(urllib.error.HTTPError) as caught:
        dv.draft_with_retry([], "k")
    assert caught.value.code == 503
    assert calls["n"] == dv.MAX_ATTEMPTS


def test_a_permanent_rejection_fails_on_the_first_attempt(monkeypatch):
    """Retrying a retired model or a bad key wastes the run and delays the
    error that tells you what is actually wrong."""
    calls = {"n": 0}

    def gone(items, key):
        calls["n"] += 1
        raise _http_error(404)

    monkeypatch.setattr(dv, "draft", gone)
    with pytest.raises(urllib.error.HTTPError):
        dv.draft_with_retry([], "k")
    assert calls["n"] == 1


def test_the_two_code_sets_never_overlap():
    assert not (dv.RETRY_CODES & dv.PERMANENT_CODES)


def test_backoff_covers_every_gap_between_attempts():
    assert len(dv.BACKOFF_SECONDS) == dv.MAX_ATTEMPTS - 1
