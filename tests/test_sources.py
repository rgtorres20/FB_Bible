"""Registry invariants for the feed source list. No network.

These are cheap tests guarding an expensive failure. A source with a broken
field does not raise anywhere -- it degrades to "no new items", which on the
board is indistinguishable from a quiet news day (sources.py says so in its
own docstring). So the shape of every entry is asserted here, at import time,
where a bad edit fails the build instead of silently thinning the wire.

Deliberately *not* tested: whether the URLs are live. That needs the network,
and the suite must pass without it. Liveness is `verify-live.yml`'s job.
"""

import dataclasses
import importlib

import pytest

from app.feeds.sources import FEED_SOURCES, SOURCES_BY_KEY, Source

# How the poller dispatches a response body. Adding a value here without
# adding the module is the mistake this set exists to catch.
SUPPORTED_PARSERS = {"rss", "rotoworld"}


def test_the_registry_is_not_empty():
    """A registry that lost its sources polls nothing and reports success."""
    assert len(FEED_SOURCES) >= 1
    assert all(isinstance(s, Source) for s in FEED_SOURCES)


def test_keys_are_unique():
    """Keys index SOURCES_BY_KEY, stamp every item and scope its dedupe id.
    A duplicate key silently drops one source out of the by-key map."""
    keys = [s.key for s in FEED_SOURCES]
    assert len(keys) == len(set(keys)), f"duplicate source key in {keys}"
    assert all(s.key for s in FEED_SOURCES)


def test_urls_are_present_and_https():
    """Plain http would be downgraded or blocked in the serverless runtime,
    and an empty URL fetches nothing while still reporting a source."""
    for source in FEED_SOURCES:
        assert source.url, f"{source.key} has no url"
        assert source.url.startswith("https://"), f"{source.key} is not https: {source.url}"


def test_urls_are_unique():
    """Two entries pointing at one feed double every item it publishes."""
    urls = [s.url for s in FEED_SOURCES]
    assert len(urls) == len(set(urls)), f"duplicate feed url in {urls}"


def test_tier_is_one_or_two():
    """The module documents 1 = report as fact, 2 = analysis/opinion, and the
    app renders it as a TIER badge. A third value renders as nothing."""
    for source in FEED_SOURCES:
        assert source.tier in (1, 2), f"{source.key} has tier {source.tier}"


def test_every_source_has_an_attribution():
    """Not cosmetic: docs/LICENSING.md records that some publishers *require*
    the credit, and it travels with the per-source status so the UI can print
    it. An empty string prints an uncredited feed."""
    for source in FEED_SOURCES:
        assert source.attribution.strip(), f"{source.key} has no attribution"


def test_every_source_has_a_display_name():
    """The name is what the board and Data Health show; the key is internal."""
    for source in FEED_SOURCES:
        assert source.name.strip(), f"{source.key} has no name"


def test_budget_hours_is_positive():
    """budget_hours is the age at which Data Health calls a feed STALE. Zero
    or negative would mark a just-fetched feed stale on arrival."""
    for source in FEED_SOURCES:
        assert isinstance(source.budget_hours, int)
        assert source.budget_hours > 0, f"{source.key} has budget_hours {source.budget_hours}"


def test_parser_is_a_supported_value():
    for source in FEED_SOURCES:
        assert source.parser in SUPPORTED_PARSERS, f"{source.key} names parser {source.parser!r}"


def test_every_named_parser_exists_in_the_codebase():
    """A parser name is a string, so a typo type-checks fine and then fails
    at poll time as "no new items". Resolve each one to a real module with a
    real parse() instead."""
    for parser in {s.parser for s in FEED_SOURCES}:
        module = importlib.import_module(f"app.feeds.{parser}")
        assert callable(getattr(module, "parse", None)), f"app.feeds.{parser} has no parse()"


def test_the_rotoworld_source_survived_the_tuple_rebuild():
    """sources.py appends Rotoworld by rebinding FEED_SOURCES to a new tuple.
    An edit that assigns instead of splices drops the six RSS feeds -- or
    drops Rotoworld -- without any error."""
    keys = {s.key for s in FEED_SOURCES}
    assert "rotoworld_pn" in keys
    assert len(keys) > 1
    assert SOURCES_BY_KEY["rotoworld_pn"].parser == "rotoworld"


def test_sources_by_key_covers_every_source_and_nothing_else():
    """It is the lookup the routes use; anything missing from it is a source
    the rest of the app cannot see."""
    assert set(SOURCES_BY_KEY) == {s.key for s in FEED_SOURCES}
    assert len(SOURCES_BY_KEY) == len(FEED_SOURCES)
    for key, source in SOURCES_BY_KEY.items():
        assert source.key == key
        assert source is next(s for s in FEED_SOURCES if s.key == key)


def test_sources_are_frozen_and_hashable():
    """Frozen dataclasses: the registry is read at import and shared across
    requests, so a route must not be able to mutate a budget or a URL."""
    source = FEED_SOURCES[0]
    assert len(set(FEED_SOURCES)) == len(FEED_SOURCES)  # hashable, and distinct
    with pytest.raises(dataclasses.FrozenInstanceError):
        source.url = "https://evil.example/rss"
