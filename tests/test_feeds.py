"""Feed parsing and merge tests. No network."""

from datetime import UTC, datetime, timedelta

from app.feeds import poller, rss

RSS2 = """<?xml version="1.0"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel>
  <item>
    <title><![CDATA[Falcons' Pearce suspended 8 games after arrest]]></title>
    <description><![CDATA[<p>Falcons edge rusher James Pearce Jr. will be
      suspended for eight games.</p>]]></description>
    <dc:creator><![CDATA[Marc Raimondi]]></dc:creator>
    <link><![CDATA[https://espn.com/nfl/story/1]]></link>
    <pubDate>Fri, 14 Aug 2026 20:53:51 EST</pubDate>
    <guid isPermaLink="false">US-EN-1</guid>
  </item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Nacua expected back next week</title>
    <summary>McVay says the psoas soreness is short-term.</summary>
    <link href="https://example.com/nacua"/>
    <id>tag:example.com,2026:nacua</id>
    <published>2026-08-14T18:00:00Z</published>
  </entry>
</feed>"""


def test_parses_rss2_with_cdata_and_html():
    items = rss.parse(RSS2, "espn", "ESPN NFL", 1)
    assert len(items) == 1
    item = items[0]
    assert item.title == "Falcons' Pearce suspended 8 games after arrest"
    assert item.link == "https://espn.com/nfl/story/1"
    assert item.author == "Marc Raimondi"
    # HTML stripped, whitespace collapsed
    assert "<p>" not in item.summary
    assert "  " not in item.summary
    assert item.summary.startswith("Falcons edge rusher")


def test_parses_atom_including_link_href():
    items = rss.parse(ATOM, "x", "X", 1)
    assert len(items) == 1
    assert items[0].link == "https://example.com/nacua"
    assert items[0].published == "2026-08-14T18:00:00+00:00"


def test_rfc822_with_named_timezone_normalises_to_utc():
    # Real ESPN feeds send "EST", which is the obsolete form.
    assert rss.parse_date("Fri, 14 Aug 2026 20:53:51 EST") == "2026-08-15T01:53:51+00:00"


def test_bad_dates_do_not_raise():
    for bad in [None, "", "not a date", "Fri, 99 Xxx"]:
        assert rss.parse_date(bad) is None


def test_malformed_xml_returns_empty_not_exception():
    """One broken feed must not fail a sync of five."""
    assert rss.parse("<rss><channel><item>", "x", "X", 1) == []
    assert rss.parse(b"\x00 not xml", "x", "X", 1) == []


def test_summary_is_truncated_at_a_word_boundary():
    long = "word " * 200
    xml = (
        f"<rss><channel><item><title>t</title>"
        f"<description>{long}</description></item></channel></rss>"
    )
    summary = rss.parse(xml, "x", "X", 1)[0].summary
    assert len(summary) <= rss.SUMMARY_LIMIT + 1  # +1 for the ellipsis
    assert summary.endswith("…")
    assert not summary.endswith("wor…")


def test_ids_are_stable_and_source_scoped():
    first = rss.parse(RSS2, "espn", "ESPN NFL", 1)[0]
    again = rss.parse(RSS2, "espn", "ESPN NFL", 1)[0]
    other_source = rss.parse(RSS2, "cbs", "CBS", 2)[0]

    assert first.id == again.id  # re-polling is a no-op
    assert first.id != other_source.id  # same story, two outlets, both kept


def test_items_without_title_or_link_are_skipped():
    xml = "<rss><channel><item><description>orphan</description></item></channel></rss>"
    assert rss.parse(xml, "x", "X", 1) == []


NOW = datetime(2026, 8, 15, tzinfo=UTC)


def item(id_: str, days_old: int = 0) -> dict:
    return {
        "id": id_,
        "published": (NOW - timedelta(days=days_old)).isoformat(),
        "title": id_,
    }


def test_merge_adds_new_and_reports_them():
    result = poller.merge({"items": [item("a")]}, [item("b")], NOW)
    assert result["new_ids"] == ["b"]
    assert {i["id"] for i in result["items"]} == {"a", "b"}


def test_merge_keeps_items_that_scrolled_off_the_feed():
    """Rotowire only exposes 5 items; replacing would lose history."""
    result = poller.merge({"items": [item("old")]}, [item("new")], NOW)
    assert {i["id"] for i in result["items"]} == {"old", "new"}


def test_repolling_the_same_item_adds_nothing():
    stored = {"items": [item("a")]}
    result = poller.merge(stored, [item("a")], NOW)
    assert result["new_ids"] == []
    assert len(result["items"]) == 1


def test_merge_drops_items_past_the_age_cutoff():
    result = poller.merge({}, [item("fresh", 1), item("ancient", 90)], NOW)
    assert {i["id"] for i in result["items"]} == {"fresh"}


def test_merge_sorts_newest_first():
    result = poller.merge({}, [item("old", 5), item("new", 0), item("mid", 2)], NOW)
    assert [i["id"] for i in result["items"]] == ["new", "mid", "old"]


def test_merge_tolerates_undated_items():
    result = poller.merge({}, [{"id": "x", "title": "x"}, item("dated")], NOW)
    assert len(result["items"]) == 2


def test_freshness_states():
    fresh = {"ok": True, "fetched_at": NOW.isoformat(), "budget_hours": 24}
    assert poller.freshness(fresh, NOW) == "LIVE"

    old = {"ok": True, "fetched_at": (NOW - timedelta(hours=48)).isoformat(), "budget_hours": 24}
    assert poller.freshness(old, NOW) == "STALE"

    assert poller.freshness({"ok": False, "error": "HTTP 500"}, NOW) == "FAILED"
    assert poller.freshness({"ok": True}, NOW) == "STALE"


def test_html_entities_are_decoded_including_double_escaped():
    """Live feeds ship "Jets&amp;#39; Geno Smith" -- escaped twice."""
    xml = (
        "<rss><channel><item>"
        "<title>Jets&amp;#39; Geno Smith has sore ankle</title>"
        "<description>Cowboys &amp;amp; Giants split &amp;quot;reps&amp;quot;</description>"
        "</item></channel></rss>"
    )
    item = rss.parse(xml, "x", "X", 1)[0]
    assert item.title == "Jets' Geno Smith has sore ankle"
    assert item.summary == 'Cowboys & Giants split "reps"'


# --- Rotoworld page parsing (fixture carved from the real page, Aug 15) ----


def test_rotoworld_parses_real_page_structure():
    from pathlib import Path

    from app.feeds import rotoworld

    html = Path("tests/fixtures/rotoworld_sample.html").read_text(encoding="utf-8")
    items = rotoworld.parse(html)

    assert len(items) == 2
    first = items[0]
    assert first["source_key"] == "rotoworld_pn"
    assert first["tier"] == 1
    assert first["published"].startswith("2026-08-15T")
    assert first["players"][0]["name"] == "Omar Cooper"
    assert first["players"][0]["position"] == "WR"
    assert first["players"][0]["team"] == "NYJ"
    assert first["title"].startswith("Jets WR Omar Cooper")
    # Their analysis is their product: truncated, and the link goes back.
    assert len(first["summary"]) <= 281
    assert first["link"].startswith("https://www.nbcsports.com/")


def test_rotoworld_junk_input_parses_to_empty():
    from app.feeds import rotoworld

    assert rotoworld.parse("<html>nothing here</html>") == []
    assert rotoworld.parse("") == []


def test_tagger_enriches_but_never_clobbers_seeded_players():
    """Rotoworld names its player structurally; the tagger adds id/rank when
    the index knows them and must not replace the seeded entry."""
    from app.feeds import players as players_mod

    index = players_mod.build_index(
        {
            "9493": {
                "active": True,
                "position": "WR",
                "full_name": "Puka Nacua",
                "team": "LAR",
                "injury_status": None,
                "search_rank": 4,
            }
        }
    )
    seeded = {
        "title": "Rams WR Puka Nacua practiced fully",
        "summary": "",
        "players": [{"id": "rw:puka-nacua", "name": "Puka Nacua", "position": "WR", "team": None}],
    }
    unknown = {
        "title": "Jets WR Omar Cooper caught 2-of-3 targets",
        "summary": "",
        "players": [
            {"id": "rw:omar-cooper", "name": "Omar Cooper", "position": "WR", "team": "NYJ"}
        ],
    }
    players_mod.tag_items([seeded, unknown], index)

    assert seeded["players"][0]["id"] == "9493"  # enriched to the index id
    assert seeded["players"][0]["rank"] == 4
    assert seeded["players"][0]["team"] == "LAR"  # filled from the index
    assert unknown["players"][0]["id"] == "rw:omar-cooper"  # unknown stays seeded
    assert unknown["players"][0]["team"] == "NYJ"


async def test_rotoworld_fetch_raises_on_empty_page():
    """A page with zero posts is a broken scrape, not a quiet day -- fetch
    must raise so the poller marks the source FAILED instead of serving an
    empty NBC tab as if it were news."""
    import httpx
    import pytest

    from app.feeds import rotoworld

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, text="<html>empty</html>"))
    ) as client_:
        with pytest.raises(ValueError, match="0 posts"):
            await rotoworld.fetch(client_)


async def test_rotoworld_fetch_surfaces_http_errors():
    import httpx
    import pytest

    from app.feeds import rotoworld

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(503))
    ) as client_:
        with pytest.raises(httpx.HTTPStatusError):
            await rotoworld.fetch(client_)


async def test_rotoworld_fetch_parses_the_real_page_shape():
    from pathlib import Path

    import httpx

    from app.feeds import rotoworld

    html = Path("tests/fixtures/rotoworld_sample.html").read_text(encoding="utf-8")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, text=html))
    ) as client_:
        items = await rotoworld.fetch(client_)
    assert items and items[0]["source_key"] == "rotoworld_pn"


# --- first_seen: what "new since last visit" is built on -------------------


def test_merge_stamps_first_seen_on_new_items():
    result = poller.merge({}, [item("a")], NOW)
    assert result["items"][0]["first_seen"] == NOW.isoformat()


def test_merge_preserves_first_seen_when_a_headline_is_edited():
    """Publishers edit posted stories; an edit is not a new arrival."""
    earlier = NOW - timedelta(hours=5)
    first = poller.merge({}, [item("a")], earlier)

    edited = {**item("a"), "title": "edited headline"}
    second = poller.merge({"items": first["items"]}, [edited], NOW)

    got = second["items"][0]
    assert got["title"] == "edited headline"
    assert got["first_seen"] == earlier.isoformat()


def test_merge_leaves_pre_feature_items_unstamped():
    """Items stored before the field existed have an unknown arrival time.
    Stamping them now would badge three-day-old stories as new."""
    stored = {"items": [item("a")]}
    result = poller.merge(stored, [item("a")], NOW)
    assert "first_seen" not in result["items"][0]


def test_merge_does_not_mutate_the_fresh_input():
    fresh = item("a")
    poller.merge({}, [fresh], NOW)
    assert "first_seen" not in fresh


# --- rotoworld's remaining edges --------------------------------------------
# The happy path and pure junk were covered; these are the shapes a real
# page degrades into, where a partial block must be skipped rather than
# emitted half-built or allowed to raise.


def test_rotoworld_shares_the_rss_cleaner_so_the_escaping_fix_covers_it():
    """`rotoworld` imports `_clean` from `rss`, so the Aug 21 fix — strip
    and unescape alternately, so nothing that becomes a tag survives —
    protects both wires. This pins that they stay one implementation: two
    cleaners is how one of them stays broken."""
    from app.feeds import rotoworld, rss

    assert rotoworld._clean is rss._clean
    html = (
        '<h2 class="PlayerNewsPost-name"><span class="PlayerNewsPost-firstName">Geno'
        '</span> <span class="PlayerNewsPost-lastName">Smith</span></h2>'
        '<h3 class="PlayerNewsPost-headline">Smith out '
        "&amp;lt;script&amp;gt;alert(1)&amp;lt;/script&amp;gt;</h3>"
    )
    items = rotoworld.parse(html)
    assert items, "the fixture has to actually parse, or this proves nothing"
    for item in items:
        assert "<script" not in item["title"]


def test_rotoworld_skips_a_block_with_no_headline():
    """A block that parsed but carries no headline is not a news item.
    Emitting it would put a blank row on the wire."""
    from app.feeds import rotoworld

    html = (
        '<h2 class="PlayerNewsPost-name"><span class="PlayerNewsPost-firstName">Omar'
        '</span> <span class="PlayerNewsPost-lastName">Cooper</span></h2>'
    )
    assert rotoworld.parse(html) == []


def test_rotoworld_keeps_a_headline_with_no_player_attached():
    """The other direction: a real headline with no name block is still
    news, and dropping it would silently thin the wire."""
    from app.feeds import rotoworld

    html = (
        '<h2 class="PlayerNewsPost-name"></h2>'
        '<h3 class="PlayerNewsPost-headline">Bills sign a kicker</h3>'
    )
    items = rotoworld.parse(html)
    assert len(items) == 1
    assert items[0]["title"] == "Bills sign a kicker"
    assert items[0]["link"] == rotoworld.URL, "falls back to the wire's own page"


def test_rotoworld_ids_are_stable_across_parses():
    """The dedupe upstream is by id. An id that changed per fetch would
    re-announce every story every hour."""
    from pathlib import Path

    from app.feeds import rotoworld

    html = Path("tests/fixtures/rotoworld_sample.html").read_text(encoding="utf-8")
    assert [i["id"] for i in rotoworld.parse(html)] == [i["id"] for i in rotoworld.parse(html)]


def test_rotoworld_ids_distinguish_different_players():
    from pathlib import Path

    from app.feeds import rotoworld

    html = Path("tests/fixtures/rotoworld_sample.html").read_text(encoding="utf-8")
    ids = [i["id"] for i in rotoworld.parse(html)]
    assert len(ids) == len(set(ids)), "two stories collapsing into one id would hide news"


def test_an_item_trimmed_at_the_cap_is_not_new_again_when_it_returns():
    """Undated items sort last and are trimmed first at the 400-item cap.
    If the publisher still carries one, the next poll re-added it as
    brand new -- first_seen restamped, NEW badge forever. The merge now
    remembers trimmed arrivals (bounded) and restores them."""
    from datetime import UTC, datetime

    from app.feeds import poller

    t0 = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    t1 = datetime(2026, 8, 20, 13, 0, tzinfo=UTC)
    old_item = {"id": "undated", "title": "No date on this one", "summary": "", "published": ""}
    first = poller.merge({}, [old_item], t0)
    assert first["items"][0]["first_seen"] == t0.isoformat()

    # Fill the store past the cap with dated items so the undated one is trimmed.
    flood = [
        {
            "id": f"i{n}",
            "title": f"story {n}",
            "summary": "",
            "published": f"2026-08-20T{10 + n % 12:02d}:{n % 60:02d}:00+00:00",
        }
        for n in range(poller.MAX_ITEMS + 5)
    ]
    capped = poller.merge({"items": first["items"], "retired": first.get("retired")}, flood, t0)
    assert all(i["id"] != "undated" for i in capped["items"]), "trimmed at the cap"
    assert capped["retired"]["undated"] == t0.isoformat()

    # The publisher still carries it; it comes back on the next poll,
    # once the flood has aged out enough to leave room on the board.
    returned = poller.merge(
        {"items": capped["items"][:50], "retired": capped["retired"]}, [old_item], t1
    )
    back = next(i for i in returned["items"] if i["id"] == "undated")
    assert back["first_seen"] == t0.isoformat(), "its first arrival, not the re-add"
    assert "undated" not in returned["new_ids"]
    assert "undated" not in returned["retired"], "carried items are not also retired"


def test_the_memory_of_trimmed_arrivals_is_bounded_and_keeps_the_recent_ones():
    """That memory is the price of not re-badging returning items NEW, and
    it is paid in the stored blob: every id ever trimmed, forever,
    re-serialised on every sync. So it is bounded at MAX_RETIRED -- and
    bounded *newest-first*, because an item trimmed this week is the one
    a publisher might still be carrying. Dropping the recent stamps to
    keep January's would hold the map small while defeating what it is
    for, and nothing else in the app would notice."""
    from datetime import UTC, datetime

    from app.feeds import poller

    now = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    # Twice the cap, oldest first, so the trim has exactly one right answer.
    remembered = {
        f"gone{n:04d}": datetime(2026, 1, 1, tzinfo=UTC).replace(microsecond=n).isoformat()
        for n in range(poller.MAX_RETIRED * 2)
    }
    kept = poller.merge({"items": [], "retired": remembered}, [], now)["retired"]

    assert len(kept) == poller.MAX_RETIRED
    # The newest half survives whole; the oldest half is what went.
    assert set(kept) == set(list(remembered)[poller.MAX_RETIRED :])
    assert all(kept[k] == remembered[k] for k in kept), "stamps are carried, not restamped"
