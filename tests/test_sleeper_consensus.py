"""The community consensus: the wire's sleeper talk, read and ranked nightly.

The other half of the owner's Aug 25 ask — the watchlist answered "whose
believer am I", this answers "who is everyone else recommending". A
nightly job (scripts/fetch_sleepers.py) reads full articles, has the AI
reader classify each author's actual stance per player, blends the
positive calls with Sleeper's add/drop trends, and pushes the ranked list
to /internal/sleepers; the Sleepers tab renders it under the owner's own
list, dated and credited.

What these tests pin, in the repo's own failure vocabulary: pushed rows
are rebuilt field by field before they can render (the vegas rule), an
empty push cannot wipe a real list (the verdict-wipe class), a stance the
model is unsure of is dropped rather than inflated (no false positives),
and dissent is reported beside the score rather than averaged away.
"""

from __future__ import annotations

import json
import re
import urllib.error
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import main as _main
from app.config import get_settings as _get_settings
from app.feeds import players, watchlist
from app.feeds.store import FileFeedStore
from app.routes import feeds as _feeds_route
from scripts import fetch_sleepers as fs

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def _mention(source="PFF", published="2026-08-27T12:00:00+00:00", verdict="sleeper", **kw):
    return {
        "source": source,
        "title": kw.get("title", "an article"),
        "url": kw.get("url", "https://x/a"),
        "published": published,
        "verdict": verdict,
        "reason": kw.get("reason", "earning work"),
    }


# --- the stance filter: no false positives ---------------------------------


def test_a_mere_mention_is_not_a_stance():
    """Most candidates are context — a teammate, a comparison. Counting
    them would make every article a recommendation of everyone in it."""
    assert not fs.keep_stance({"verdict": "mentioned", "confidence": 0.95})


def test_an_unsure_model_is_dropped_not_inflated():
    assert not fs.keep_stance({"verdict": "sleeper", "confidence": 0.39})
    assert fs.keep_stance({"verdict": "sleeper", "confidence": 0.4})


def test_negative_stances_count_as_stances():
    """A fade is kept — not to score it, but to report the dissent."""
    assert fs.keep_stance({"verdict": "bust", "confidence": 0.8})


def test_junk_confidence_reads_as_no_stance():
    assert not fs.keep_stance({"verdict": "sleeper", "confidence": "high"})
    assert not fs.keep_stance({"verdict": "sleeper"})
    assert not fs.keep_stance({"verdict": "invented-verdict", "confidence": 0.9})


def test_fenced_json_is_unwrapped():
    """Models love a code fence; stripping it is cheaper than failing."""
    bare = '[{"a": 1}]'
    assert fs._strip_fence(bare) == bare
    assert fs._strip_fence(f"```json\n{bare}\n```") == bare
    assert fs._strip_fence(f"```\n{bare}\n```") == bare


# --- candidate matching: the app's matcher, the leagues' positions ----------


def _index():
    return players.build_index(
        {
            "1": {
                "active": True,
                "full_name": "Blake Corum",
                "position": "RB",
                "team": "LAR",
                "search_rank": 1,
            },
            "2": {
                "active": True,
                "full_name": "Edgerrin Cooper",
                "position": "LB",
                "fantasy_positions": ["LB"],
                "team": "GB",
                "search_rank": 2,
            },
            "3": {
                "active": True,
                "full_name": "Jake Bates",
                "position": "K",
                "team": "DET",
                "search_rank": 3,
            },
            "4": {
                "active": True,
                "position": "DEF",
                "first_name": "Detroit",
                "last_name": "Lions",
                "team": "DET",
            },
        }
    )


def test_defenders_are_candidates_because_the_leagues_start_eight():
    """QB/RB/WR/TE-only was the mistake /app/nextup already had to fix:
    both verified leagues are IDP (docs/LEAGUES.md)."""
    text = "Blake Corum and Edgerrin Cooper are risers; Jake Bates kicks."
    names = {c["name"] for c in fs.candidates_in(text, _index())}
    assert names == {"Blake Corum", "Edgerrin Cooper"}


def test_team_defenses_and_kickers_are_not_sleeper_candidates():
    """A city name in a headline is a story about a team; a kicker is not
    what a sleeper article is recommending."""
    text = "The Detroit Lions look strong and Jake Bates has range."
    assert fs.candidates_in(text, _index()) == []


# --- the ranking: consensus × recency, penalized by ownership ---------------


def test_one_source_one_old_call_scores_one():
    rows = fs.rank_consensus(
        {"1": [_mention(published="2026-08-20T12:00:00+00:00")]},
        {"1": {"name": "Blake Corum", "position": "RB", "team": "LAR"}},
        {},
        {},
        {},
        now=NOW,
    )
    assert rows[0]["score"] == 1.0


def test_a_call_this_week_counts_double():
    rows = fs.rank_consensus(
        {"1": [_mention(published="2026-08-27T12:00:00+00:00")]},
        {"1": {"name": "Blake Corum", "position": "RB", "team": "LAR"}},
        {},
        {},
        {},
        now=NOW,
    )
    assert rows[0]["score"] == 2.0


def test_widely_rostered_players_are_not_sleepers():
    """The divisor is the point: a player everyone already holds is not a
    sleeper whatever the wire says about him."""
    args = (
        {"1": [_mention(published="2026-08-20T12:00:00+00:00")]},
        {"1": {"name": "Blake Corum", "position": "RB", "team": "LAR"}},
        {},
        {},
    )
    free = fs.rank_consensus(*args, {}, now=NOW)[0]["score"]
    held = fs.rank_consensus(*args, {"1": 20.0}, now=NOW)[0]["score"]
    assert held == pytest.approx(free / 2)


def test_dissent_is_reported_beside_the_score_never_subtracted():
    """ "Three sites love him, one is out" is a finding the reader should
    see; an average would hide both halves."""
    rows = fs.rank_consensus(
        {
            "1": [
                _mention(published="2026-08-20T12:00:00+00:00"),
                _mention(
                    source="Razzball",
                    verdict="fade",
                    published="2026-08-20T13:00:00+00:00",
                ),
            ]
        },
        {"1": {"name": "Blake Corum", "position": "RB", "team": "LAR"}},
        {},
        {},
        {},
        now=NOW,
    )
    assert rows[0]["dissent_count"] == 1
    assert rows[0]["score"] == 1.0, "the fade informed nothing but the dissent column"


def test_a_trending_spike_cannot_outrank_a_second_source():
    """Tuned Aug 29, owner call, from the first live run: roster-cut week
    put a one-article player at 60,579 adds and (adds/1000) multiplied
    his single mention 61x past every real consensus. Buzz leans; a
    second writer always outweighs any amount of it."""
    spike = fs.rank_consensus(
        {"1": [_mention()]},
        {"1": {"name": "One Article", "position": "WR", "team": "CIN"}},
        {"1": 60579},
        {},
        {},
        now=NOW,
    )[0]
    agreed = fs.rank_consensus(
        {"2": [_mention(), _mention(source="Razzball", url="https://x/b")]},
        {"2": {"name": "Two Writers", "position": "RB", "team": "HOU"}},
        {},
        {},
        {},
        now=NOW,
    )[0]

    assert agreed["score"] > spike["score"]
    assert spike["trending_adds_72h"] == 60579, "the spike stays visible on the row"


def test_buzz_doubles_at_most_and_halves_at_most():
    args = (
        {"1": [_mention(published="2026-08-20T12:00:00+00:00")]},
        {"1": {"name": "Blake Corum", "position": "RB", "team": "LAR"}},
    )
    plain = fs.rank_consensus(*args, {}, {}, {}, now=NOW)[0]["score"]
    spiked = fs.rank_consensus(*args, {"1": 10**6}, {}, {}, now=NOW)[0]["score"]
    dumped = fs.rank_consensus(*args, {}, {"1": 10**6}, {}, now=NOW)[0]["score"]

    assert spiked == pytest.approx(plain * 2)
    assert dumped == pytest.approx(plain / 2)


def test_a_player_with_only_negative_calls_is_not_on_the_list():
    """This is a sleeper list, not a bust list. A pure fade consensus is
    a different surface; inventing a row for it here would file a warning
    under a heading that says "recommended"."""
    rows = fs.rank_consensus(
        {"1": [_mention(verdict="bust")]},
        {"1": {"name": "Blake Corum", "position": "RB", "team": "LAR"}},
        {},
        {},
        {},
        now=NOW,
    )
    assert rows == []


def test_defenders_report_the_group_their_leagues_start():
    """DB/LB/DL, not MIKE or WILL — the same vocabulary as /app/nextup,
    because that is the slot a league actually fills."""
    rows = fs.rank_consensus(
        {"2": [_mention()]},
        {"2": {"name": "Edgerrin Cooper", "position": "LB", "idp": "LB", "team": "GB"}},
        {},
        {},
        {},
        now=NOW,
    )
    assert rows[0]["position"] == "LB"


def test_links_are_newest_first_and_capped():
    mentions = [
        _mention(published=f"2026-08-{day:02d}T12:00:00+00:00", url=f"https://x/{day}")
        for day in range(18, 25)
    ]
    rows = fs.rank_consensus(
        {"1": mentions},
        {"1": {"name": "Blake Corum", "position": "RB", "team": "LAR"}},
        {},
        {},
        {},
        now=NOW,
    )
    urls = [link["url"] for link in rows[0]["links"]]
    assert urls == [f"https://x/{day}" for day in (24, 23, 22, 21, 20)]


# --- the push endpoint: rebuilt field by field ------------------------------


@pytest.fixture
def push_client(tmp_path, monkeypatch):
    monkeypatch.setattr(_get_settings(), "sync_token", "secret-token", raising=False)
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    _main.app.dependency_overrides[_feeds_route.get_feed_store] = lambda: store
    _main.app.dependency_overrides[_feeds_route.get_optional_feed_store] = lambda: store
    yield TestClient(_main.app), store
    _main.app.dependency_overrides.clear()


def _row(**kw):
    return {
        "player_id": "1",
        "name": "Blake Corum",
        "position": "RB",
        "team": "LAR",
        "score": 4.2,
        "source_count": 2,
        "mention_count": 3,
        "dissent_count": 0,
        "trending_adds_72h": 900,
        "roster_pct": 12.5,
        "reasons": ["earning early-down work"],
        "links": [
            {
                "source": "PFF",
                "title": "an article",
                "url": "https://x/a",
                "published": "2026-08-27T12:00:00+00:00",
            }
        ],
        **kw,
    }


async def test_push_requires_the_sync_token(push_client):
    c, _ = push_client
    response = c.post("/internal/sleepers", json={"state": {"players": [_row()]}})
    assert response.status_code == 401


async def test_push_sanitizes_rows_to_known_fields(push_client):
    """Pushed rows render into the page, so only the known columns pass —
    injected keys, non-dict rows, nameless rows and non-http links die."""
    c, store = push_client
    response = c.post(
        "/internal/sleepers",
        json={
            "state": {
                "season": "2026",
                "article_count": 17,
                "sources_surveyed": ["PFF", "Razzball"],
                "players": [
                    _row(evil="<script>", links=[{"url": "javascript:alert(1)"}]),
                    {"score": 9.9},
                    "not-a-dict",
                ],
            }
        },
        headers={"X-Sync-Token": "secret-token"},
    )

    assert response.json()["stored"] == 1
    saved = (await store.load())["sleeper_consensus"]
    row = saved["players"][0]
    assert "evil" not in row
    assert row["links"] == [], "a link that is not http(s) must never become an anchor"
    assert row["name"] == "Blake Corum"
    assert saved["article_count"] == 17
    assert saved["fetched_at"], "the as-of stamp is the server's, not the pusher's"


async def test_an_empty_push_cannot_wipe_a_real_list(push_client):
    """The verdict-wipe class: a bad night at the publishers must not
    replace a stored consensus with nothing."""
    c, store = push_client
    c.post(
        "/internal/sleepers",
        json={"state": {"players": [_row()]}},
        headers={"X-Sync-Token": "secret-token"},
    )
    response = c.post(
        "/internal/sleepers",
        json={"state": {"players": []}},
        headers={"X-Sync-Token": "secret-token"},
    )

    assert response.status_code == 422
    saved = await store.load()
    assert saved["sleeper_consensus"]["players"], "the stored list survived"


def test_junk_numbers_are_coerced_not_served():
    rows = watchlist.clean_consensus(
        [_row(score="not-a-number", trending_adds_72h=-5, roster_pct="12.5")]
    )
    assert rows[0]["score"] == 0.0
    assert rows[0]["trending_adds_72h"] == 0
    assert rows[0]["roster_pct"] == 12.5


def test_the_row_cap_holds():
    rows = watchlist.clean_consensus([_row(name=f"P {i}") for i in range(60)])
    assert len(rows) == watchlist.MAX_CONSENSUS_ROWS


# --- the tab's payload ------------------------------------------------------


async def test_the_tab_serves_the_consensus_once_stored(push_client):
    c, _ = push_client
    c.post(
        "/internal/sleepers",
        json={"state": {"players": [_row()], "article_count": 9}},
        headers={"X-Sync-Token": "secret-token"},
    )

    payload = c.get("/app/data/sleepers.json").json()

    assert payload["consensus"]["players"][0]["name"] == "Blake Corum"
    assert "Sleeper" in payload["consensus"]["attribution"], (
        "the trend data credit travels with the numbers (docs/LICENSING.md)"
    )


async def test_no_push_yet_means_no_consensus_not_an_empty_frame(push_client):
    """Absent is honest; an empty section under a live-sounding heading
    is not. The panel renders nothing until the first push lands."""
    c, _ = push_client
    payload = c.get("/app/data/sleepers.json").json()
    assert payload["consensus"] is None


def test_a_junk_block_in_the_store_reads_as_none():
    for junk in (None, {}, {"players": []}, {"players": "nope"}, "nope"):
        assert watchlist.consensus(junk) is None


# --- batched classification -------------------------------------------------
#
# One model call per BATCH_SIZE articles, not one per article. The
# per-article version made 40 calls a night and the free tier's throttle
# marched every one through the full backoff ladder — the first two live
# runs took 38 and 58 minutes. Same lesson the verdicts job bought on
# Aug 18: calls fight each other for one quota.


def _wire(monkeypatch, reply_fn, candidates_fn=None):
    """The non-model plumbing, stubbed identically across these tests."""
    calls: list[list[str]] = []

    def chat(messages, api_key):
        keys = re.findall(r"ARTICLE (a\d+) ", messages[1]["content"])
        calls.append(keys)
        return {"choices": [{"message": {"content": reply_fn(keys)}}]}

    monkeypatch.setattr(fs, "chat_with_retry", chat)
    monkeypatch.setattr(fs, "article_text", lambda item: "x" * 500)
    monkeypatch.setattr(fs, "candidates_in", candidates_fn or (lambda text, index: [_candidate()]))
    monkeypatch.setattr(fs, "fetch_trending", lambda *a, **k: {})
    monkeypatch.setattr(fs, "fetch_ownership", lambda: {})
    monkeypatch.setattr(fs, "AI_CALL_DELAY", 0)
    return calls


def _items(n):
    return [
        {
            "source": f"S{i}",
            "title": f"t{i}",
            "url": f"https://x/{i}",
            "published": "2026-08-27T12:00:00+00:00",
        }
        for i in range(n)
    ]


def test_articles_travel_in_batches_of_five(monkeypatch):
    calls = _wire(monkeypatch, lambda keys: "{}")

    _, read = fs.build_consensus(_items(12), {}, "key")

    assert [len(c) for c in calls] == [5, 5, 2], "12 articles, 3 requests"
    assert read == 12


def test_a_stance_lands_on_the_article_that_said_it(monkeypatch):
    """The rows come back keyed by article, and each article's rows are
    filtered against its OWN candidates — a stance the model files under
    the wrong article must die there, not credit a source that never
    said it."""
    per_article = {
        0: [{"id": "1", "name": "Blake Corum", "position": "RB", "team": "LAR"}],
        1: [{"id": "2", "name": "Edgerrin Cooper", "position": "LB", "team": "GB"}],
    }
    seen = iter(per_article.values())

    def reply(keys):
        return json.dumps(
            {
                "a1": [{"player_id": "1", "verdict": "sleeper", "confidence": 0.9, "reason": "r"}],
                # Filed under a2 but names a1's player: must be dropped.
                "a2": [{"player_id": "1", "verdict": "sleeper", "confidence": 0.9, "reason": "r"}],
            }
        )

    _wire(monkeypatch, reply, candidates_fn=lambda text, index: next(seen))

    rows, read = fs.build_consensus(_items(2), {}, "key")

    assert read == 2
    assert [r["name"] for r in rows] == ["Blake Corum"]
    assert [link["source"] for link in rows[0]["links"]] == ["S0"], (
        "the stance credits the article that actually said it"
    )


def test_one_garbled_reply_costs_only_its_batch(monkeypatch):
    replies = iter(["this is not json", '{"a6": []}'])
    calls = _wire(monkeypatch, lambda keys: next(replies))

    _, read = fs.build_consensus(_items(7), {}, "key")

    assert len(calls) == 2, "the second batch still ran"
    assert read == 2, "only the good batch counts as read"


def test_a_permanently_rejected_model_stops_the_run(monkeypatch):
    """Retrying a retired model eight times is a slower way to be wrong —
    the exact failure the verdicts job shipped with once. The run keeps
    what it earned and stops spending."""
    calls = []

    def rejected(*args, **kwargs):
        calls.append(1)
        raise urllib.error.HTTPError("u", 404, "gone", {}, None)

    monkeypatch.setattr(fs, "chat_with_retry", rejected)
    monkeypatch.setattr(fs, "article_text", lambda item: "x" * 500)
    monkeypatch.setattr(fs, "candidates_in", lambda text, index: [_candidate()])
    monkeypatch.setattr(fs, "fetch_trending", lambda *a, **k: {})
    monkeypatch.setattr(fs, "fetch_ownership", lambda: {})
    monkeypatch.setattr(fs, "AI_CALL_DELAY", 0)

    rows, read = fs.build_consensus(_items(12), {}, "key")

    assert calls == [1], "one rejection, no second spend — batch 2 and 3 never fire"
    assert (rows, read) == ([], 0)


def _candidate():
    return {"id": "1", "name": "Blake Corum", "position": "RB", "team": "LAR"}
