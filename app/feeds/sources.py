"""The feed registry.

Every URL here was verified to return a real RSS document before being added
(2026-08-14). Two candidates were dropped for returning 404: nfl.com's news
feed and fantasypros.com's. Check before adding — a dead feed degrades to
"no new items", which looks identical to "quiet news day".

`budget_hours` mirrors the blueprint's freshness budgets: how old a feed may
get before Data Health should call it STALE.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Source:
    key: str
    name: str
    url: str
    # 1 = report it as fact, 2 = analysis/opinion. Mirrors the app's TIER badge.
    tier: int
    budget_hours: int
    # Printed with the items. Some publishers require it; all deserve it.
    attribution: str


FEED_SOURCES: tuple[Source, ...] = (
    Source(
        key="espn",
        name="ESPN NFL",
        url="https://www.espn.com/espn/rss/nfl/news",
        tier=1,
        budget_hours=24,
        attribution="ESPN",
    ),
    Source(
        key="yahoo",
        name="Yahoo Sports NFL",
        url="https://sports.yahoo.com/nfl/rss.xml",
        tier=1,
        budget_hours=24,
        attribution="Yahoo Sports",
    ),
    Source(
        key="rotowire",
        name="Rotowire NFL",
        url="https://www.rotowire.com/rss/news.php?sport=NFL",
        tier=1,
        budget_hours=24,
        attribution="Rotowire",
    ),
    Source(
        key="pft",
        name="NBC Sports · ProFootballTalk",
        url="https://profootballtalk.nbcsports.com/feed/",
        tier=1,
        budget_hours=24,
        attribution="NBC Sports / ProFootballTalk",
    ),
    Source(
        key="cbs",
        name="CBS Sports NFL",
        url="https://www.cbssports.com/rss/headlines/nfl/",
        tier=2,
        budget_hours=24,
        attribution="CBS Sports",
    ),
)

SOURCES_BY_KEY = {s.key: s for s in FEED_SOURCES}
