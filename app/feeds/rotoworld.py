"""NBC Sports Rotoworld player news, parsed from the page itself.

Rotoworld retired its RSS feed; the player-news page is server-rendered with
stable BEM classes (PlayerNewsPost-*) and ISO timestamps in data-date, so the
page is effectively the API. Verified live before writing this: 280 posts per
fetch, every field present in raw HTML with no auth and no JS.

Posture, same as the wire (docs/LICENSING.md): their analysis paragraphs are
their product, so summaries are truncated hard and every item links back;
polled at most hourly by the same scheduler as everything else; attributed as
NBC Sports Rotoworld wherever shown.

Parsing is regex over class anchors rather than an HTML parser: the classes
are the stable contract here, the surrounding markup is generated noise, and
one malformed post must skip -- not sink -- the batch.
"""

from __future__ import annotations

import hashlib
import logging
import re

import httpx

from .rss import SUMMARY_LIMIT, _clean, _truncate

log = logging.getLogger(__name__)

URL = "https://www.nbcsports.com/fantasy/football/player-news"
SOURCE_KEY = "rotoworld_pn"
SOURCE_NAME = "NBC Rotoworld"
MAX_POSTS = 60

_BLOCK_SPLIT = re.compile(r'(?=<h2 class="PlayerNewsPost-name")')
_FIRST = re.compile(r"PlayerNewsPost-firstName[^>]*>([^<]+)<")
_LAST = re.compile(r"PlayerNewsPost-lastName[^>]*>([^<]+)<")
_NAME_LINK = re.compile(r'PlayerNewsPost-name.*?<a href="([^"]+)"', re.S)
_TEAM_ABBR = re.compile(r"PlayerNewsPost-team.*?>([A-Z]{2,3})</span>", re.S)
_POSITION = re.compile(
    r">((?:Quarterback|Running Back|Wide Receiver|Tight End|Kicker"
    r"|[A-Za-z ]+back|[A-Za-z ]+ End|Linebacker|Cornerback|Safety"
    r"|Guard|Tackle|Center)s?)<"
)
_HEADLINE = re.compile(r"PlayerNewsPost-headline[^>]*>(.*?)</h3>", re.S)
_ANALYSIS = re.compile(r"PlayerNewsPost-analysis[^>]*>(.*?)</div>", re.S)
_DATE = re.compile(r'PlayerNewsPost-date[^>]*data-date="([^"]+)"')
_TYPE = re.compile(r"PlayerNewsPost-type[^>]*>([^<]+)<")

_POSITION_ABBR = {
    "Quarterback": "QB",
    "Running Back": "RB",
    "Wide Receiver": "WR",
    "Tight End": "TE",
    "Kicker": "K",
}


def parse(html: str) -> list[dict]:
    """Extract posts as wire-item dicts. Bad blocks are skipped, not fatal."""
    items: list[dict] = []
    blocks = _BLOCK_SPLIT.split(html)

    for block in blocks[1:]:
        try:
            headline = _HEADLINE.search(block)
            if not headline:
                continue
            title = _clean(headline.group(1))
            if not title:
                continue

            first = _FIRST.search(block)
            last = _LAST.search(block)
            name = _clean(f"{first.group(1) if first else ''} {last.group(1) if last else ''}")

            date = _DATE.search(block)
            published = date.group(1) if date else None
            if published and published.endswith("Z"):
                published = published[:-1] + "+00:00"

            analysis = _ANALYSIS.search(block)
            summary = _truncate(_clean(analysis.group(1)) if analysis else "", SUMMARY_LIMIT)

            link_match = _NAME_LINK.search(block)
            link = link_match.group(1) if link_match else URL

            team = _TEAM_ABBR.search(block)
            position_match = _POSITION.search(block)
            position_full = _clean(position_match.group(1)) if position_match else ""
            fallback = position_full[:2].upper() if position_full else ""
            position = _POSITION_ABBR.get(position_full, fallback)

            kind = _TYPE.search(block)

            digest = hashlib.sha256(
                f"{SOURCE_KEY}:{name}:{published or title}".encode()
            ).hexdigest()[:16]

            items.append(
                {
                    "id": digest,
                    "source_key": SOURCE_KEY,
                    "source_name": SOURCE_NAME,
                    "tier": 1,
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "published": published,
                    "author": None,
                    "news_type": _clean(kind.group(1)) if kind else None,
                    # Pre-seeded from Rotoworld's own player fields, which are
                    # more authoritative than name-matching the headline. The
                    # tagger enriches with id/rank when the index knows the
                    # player, and must not clobber this (see tag_items).
                    "players": [
                        {
                            "id": f"rw:{re.sub(r'[^a-z0-9]+', '-', name.lower())}",
                            "name": name,
                            "position": position,
                            "team": team.group(1) if team else None,
                        }
                    ]
                    if name
                    else [],
                }
            )
            if len(items) >= MAX_POSTS:
                break
        except Exception:  # noqa: BLE001 - one bad block must not sink the batch
            log.debug("skipping malformed PlayerNewsPost block")
    return items


async def fetch(client: httpx.AsyncClient) -> list[dict]:
    response = await client.get(URL)
    response.raise_for_status()
    parsed = parse(response.text)
    if not parsed:
        raise ValueError("parsed 0 posts")
    return parsed
