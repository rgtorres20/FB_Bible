"""Minimal RSS 2.0 / Atom parser, stdlib only.

No feedparser dependency: it is a large addition to a serverless bundle for a
job this narrow, and the two date formats real feeds use are both in the
standard library.

**Summaries are truncated on purpose.** These are other people's articles. We
keep a headline, a short excerpt and — always — the link back. Storing full
article text would be republishing it. See docs/LICENSING.md.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

# Long enough to judge whether an item matters, short enough not to be a copy.
SUMMARY_LIMIT = 280

_ATOM = "{http://www.w3.org/2005/Atom}"
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


@dataclass(slots=True)
class FeedItem:
    id: str
    source_key: str
    source_name: str
    tier: int
    title: str
    summary: str
    link: str
    published: str | None  # ISO 8601 UTC, or None if the feed omitted it
    author: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def _clean(text: str | None) -> str:
    """Strip tags and collapse whitespace. Feeds routinely embed HTML."""
    if not text:
        return ""
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()


def _truncate(text: str, limit: int = SUMMARY_LIMIT) -> str:
    if len(text) <= limit:
        return text
    # Cut at a word boundary so the excerpt reads as a sentence fragment,
    # not a severed word.
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + "…"


def parse_date(raw: str | None) -> str | None:
    """RFC 822 (RSS) or ISO 8601 (Atom) -> ISO 8601 UTC string."""
    if not raw:
        return None
    raw = raw.strip()
    for parser in (parsedate_to_datetime, datetime.fromisoformat):
        try:
            parsed = parser(raw.replace("Z", "+00:00") if parser is datetime.fromisoformat else raw)
        except (TypeError, ValueError):
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat()
    return None


def _item_id(source_key: str, guid: str, link: str, title: str) -> str:
    """Stable id for dedupe. guid is preferred; some feeds omit or reuse it."""
    basis = guid or link or title
    digest = hashlib.sha256(f"{source_key}:{basis}".encode()).hexdigest()
    return digest[:16]


def _text(node, *names: str) -> str | None:
    for name in names:
        found = node.find(name)
        if found is not None:
            if found.text:
                return found.text
            # Atom <link href="..."/> carries no text.
            href = found.get("href")
            if href:
                return href
    return None


def parse(xml: bytes | str, source_key: str, source_name: str, tier: int) -> list[FeedItem]:
    """Parse a feed document. Returns [] rather than raising on junk input --
    one broken feed must not take down a sync of five."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return []

    nodes = root.findall(".//item") or root.findall(f".//{_ATOM}entry")

    items: list[FeedItem] = []
    for node in nodes:
        title = _clean(_text(node, "title", f"{_ATOM}title"))
        link = _clean(_text(node, "link", f"{_ATOM}link"))
        if not title and not link:
            continue

        summary = _clean(_text(node, "description", f"{_ATOM}summary", f"{_ATOM}content"))
        guid = _clean(_text(node, "guid", f"{_ATOM}id"))
        published = parse_date(_text(node, "pubDate", f"{_ATOM}published", f"{_ATOM}updated"))
        author = _clean(_text(node, "{http://purl.org/dc/elements/1.1/}creator", f"{_ATOM}author"))

        items.append(
            FeedItem(
                id=_item_id(source_key, guid, link, title),
                source_key=source_key,
                source_name=source_name,
                tier=tier,
                title=title,
                summary=_truncate(summary),
                link=link,
                published=published,
                author=author or None,
            )
        )
    return items
