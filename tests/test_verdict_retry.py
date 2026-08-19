"""Retry and fallback policy for every model call in the repo.

The first live run against Google AI Studio returned HTTP 503 "model
overloaded" -- a busy free tier, not a broken one. A single attempt an
hour loses the whole hour to that, while retrying a permanently dead
endpoint is just a slower way to be wrong. The split between those two is
the first contract here.

The second is the fallback chain, bought with the Aug 19 outage:
gemini-flash-latest refused every chat call for 10+ hours (503/429,
spanning the daily quota reset) while its lite sibling answered
instantly. A busy or vanished primary hands off to FALLBACK_MODEL; codes
that would fail on any model (bad key, bad request) raise immediately.
"""

from __future__ import annotations

import urllib.error

import pytest

from scripts import draft_verdicts as dv

OK = {"choices": [{"message": {"content": "{}"}}]}


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x", code, "boom", {}, None)


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch):
    monkeypatch.setattr(dv.time, "sleep", lambda _s: None)


def _record_models(monkeypatch, outcome):
    """Patch http_json to record which model each call asked for and defer
    the result to `outcome(model, call_number)`."""
    calls: list[str] = []

    def fake(url, payload=None, headers=None):
        calls.append(payload["model"])
        return outcome(payload["model"], len(calls))

    monkeypatch.setattr(dv, "http_json", fake)
    return calls


def test_a_busy_primary_is_retried_and_can_succeed(monkeypatch):
    calls = _record_models(
        monkeypatch, lambda model, n: OK if n >= 3 else (_ for _ in ()).throw(_http_error(503))
    )
    assert dv.chat_with_retry([], "k") == OK
    assert calls == [dv.MODEL] * 3


def test_an_exhausted_primary_falls_back_to_the_lite_model(monkeypatch):
    def outcome(model, n):
        if model == dv.MODEL:
            raise _http_error(503)
        return OK

    calls = _record_models(monkeypatch, outcome)
    assert dv.chat_with_retry([], "k") == OK
    assert calls == [dv.MODEL] * dv.MAX_ATTEMPTS + [dv.FALLBACK_MODEL]


def test_a_vanished_primary_falls_back_without_burning_retries(monkeypatch):
    """404 is the name-vanished failure this job has died to twice --
    retrying it is pointless, but the fallback model may well exist."""

    def outcome(model, n):
        if model == dv.MODEL:
            raise _http_error(404)
        return OK

    calls = _record_models(monkeypatch, outcome)
    assert dv.chat_with_retry([], "k") == OK
    assert calls == [dv.MODEL, dv.FALLBACK_MODEL]


def test_both_models_exhausted_surfaces_the_last_failure(monkeypatch):
    calls = _record_models(monkeypatch, lambda model, n: (_ for _ in ()).throw(_http_error(503)))
    with pytest.raises(urllib.error.HTTPError) as caught:
        dv.chat_with_retry([], "k")
    assert caught.value.code == 503
    assert len(calls) == 2 * dv.MAX_ATTEMPTS


def test_a_key_or_request_problem_fails_on_the_first_attempt(monkeypatch):
    """A 401 fails on every model alike; falling back or retrying only
    delays the error that says what is actually wrong."""
    calls = _record_models(monkeypatch, lambda model, n: (_ for _ in ()).throw(_http_error(401)))
    with pytest.raises(urllib.error.HTTPError):
        dv.chat_with_retry([], "k")
    assert calls == [dv.MODEL]


def test_the_transient_and_permanent_code_sets_never_overlap():
    assert not (dv.RETRY_CODES & dv.PERMANENT_CODES)


def test_backoff_covers_every_gap_between_attempts():
    assert len(dv.BACKOFF_SECONDS) == dv.MAX_ATTEMPTS - 1
