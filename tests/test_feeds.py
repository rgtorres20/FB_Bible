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
