"""Parser behaviour for app/feeds/rss.py. No network -- the XML is inline.

test_feeds.py already covers the happy path for one RSS item and one Atom
entry. This file is about the *degradation*: what the parser returns when a
publisher ships a truncated document, an empty channel, or an item with no
date. Those cases matter more than they look, because the poller treats an
empty parse as "parsed 0 items" and the board treats it as a quiet news day.
If the parser raised instead, one bad publisher would take the whole sync
down; if it invented a date, the freshness stamps would be fiction. So both
halves are asserted: it must not raise, and it must not fill in blanks.

XML shapes are copied from real feeds (the CDATA/creator/guid layout ESPN
sends, the double-escaped entities Yahoo sends) rather than invented.
"""

from app.feeds import rss

# The shape ESPN actually sends: CDATA everywhere, dc:creator, a non-permalink
# guid, and an RFC 822 date with an obsolete named zone.
ESPN_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel>
  <title>ESPN.com - NFL</title>
  <link>https://www.espn.com/nfl/</link>
  <item>
    <title><![CDATA[Bengals' Chase held out of practice with hamstring]]></title>
    <description><![CDATA[<p>Ja'Marr Chase did not practice Thursday, though
      Zac Taylor called it &quot;maintenance&quot;.</p>]]></description>
    <dc:creator><![CDATA[Ben Baby]]></dc:creator>
    <link><![CDATA[https://espn.com/nfl/story/chase]]></link>
    <pubDate>Thu, 20 Aug 2026 16:04:00 EST</pubDate>
    <guid isPermaLink="false">US-EN-4401</guid>
  </item>
  <item>
    <title><![CDATA[Nacua returns to full participation]]></title>
    <description><![CDATA[McVay says the psoas soreness is behind him.]]></description>
    <link><![CDATA[https://espn.com/nfl/story/nacua]]></link>
    <pubDate>Wed, 19 Aug 2026 11:30:00 GMT</pubDate>
    <guid isPermaLink="false">US-EN-4390</guid>
  </item>
</channel>
</rss>"""


def test_a_well_formed_feed_yields_every_item_with_all_four_fields():
    items = rss.parse(ESPN_FEED, "espn", "ESPN NFL", 1)

    assert len(items) == 2
    first, second = items

    assert first.title == "Bengals' Chase held out of practice with hamstring"
    assert first.link == "https://espn.com/nfl/story/chase"
    assert first.summary.startswith("Ja'Marr Chase did not practice Thursday")
    assert first.published == "2026-08-20T21:04:00+00:00"
    assert first.author == "Ben Baby"

    assert second.title == "Nacua returns to full participation"
    assert second.published == "2026-08-19T11:30:00+00:00"
    # No dc:creator on the second item -- absent, not an empty string, because
    # the UI tests it for truthiness before printing a byline.
    assert second.author is None


def test_document_order_is_preserved():
    """The poller sorts by date afterwards; the parser must not reorder, or
    an undated feed would come out shuffled."""
    titles = [i.title for i in rss.parse(ESPN_FEED, "espn", "ESPN NFL", 1)]
    assert titles == [
        "Bengals' Chase held out of practice with hamstring",
        "Nacua returns to full participation",
    ]


def test_every_item_carries_its_source_stamp():
    """Items from five feeds land in one merged list; without the stamp the
    board cannot render the tier badge or the required attribution."""
    for item in rss.parse(ESPN_FEED, "espn", "ESPN NFL", 1):
        assert item.source_key == "espn"
        assert item.source_name == "ESPN NFL"
        assert item.tier == 1


def test_cdata_titles_come_out_as_readable_text():
    """CDATA is how feeds ship apostrophes and ampersands. If the wrapper
    leaked, every headline on the board would read "<![CDATA[...".
    """
    xml = (
        "<rss><channel><item>"
        "<title><![CDATA[Ravens' Andrews & Likely split snaps]]></title>"
        "<link><![CDATA[https://e.com/1]]></link>"
        "</item></channel></rss>"
    )
    item = rss.parse(xml, "x", "X", 1)[0]
    assert item.title == "Ravens' Andrews & Likely split snaps"
    assert "CDATA" not in item.title


def test_numeric_entity_apostrophes_are_decoded():
    """Yahoo encodes apostrophes as &#39; -- singly here, doubly below. Left
    raw, a headline reads "Jets&#39; Geno Smith"."""
    xml = (
        "<rss><channel><item>"
        "<title>Jets&#39; Geno Smith cleared</title>"
        "<link>https://e.com/geno</link>"
        "</item></channel></rss>"
    )
    assert rss.parse(xml, "x", "X", 1)[0].title == "Jets' Geno Smith cleared"


def test_double_escaped_entities_are_decoded_too():
    """Yahoo ships "Jets&amp;#39; Geno Smith": escaped once by the CMS, once
    again by the feed writer. _clean unescapes twice to cover it."""
    xml = (
        "<rss><channel><item>"
        "<title>Chiefs&amp;#39; Rice &amp;amp; Worthy both active</title>"
        "<description>Reid called it &amp;quot;a full week&amp;quot;.</description>"
        "<link>https://e.com/rice</link>"
        "</item></channel></rss>"
    )
    item = rss.parse(xml, "x", "X", 1)[0]
    assert item.title == "Chiefs' Rice & Worthy both active"
    assert item.summary == 'Reid called it "a full week".'


def test_escaped_markup_in_a_description_is_stripped():
    """Feeds that escape their HTML instead of using CDATA send &lt;p&gt;.
    The excerpt must read as prose, with the tags and the newlines gone."""
    xml = (
        "<rss><channel><item><title>t</title><link>https://e.com/1</link>"
        "<description>&lt;p&gt;Hall took 18 carries.&lt;/p&gt;\n"
        "&lt;p&gt;He also saw 5 targets.&lt;/p&gt;</description>"
        "</item></channel></rss>"
    )
    summary = rss.parse(xml, "x", "X", 1)[0].summary
    assert "<p>" not in summary
    assert "\n" not in summary
    assert "  " not in summary
    assert "Hall took 18 carries." in summary
    assert "He also saw 5 targets." in summary


def test_a_non_utf8_document_is_decoded_by_its_declaration():
    """Bytes go straight from httpx to the parser, so the XML declaration is
    what resolves the encoding. Mangling it would corrupt accented names."""
    raw = (
        "<?xml version='1.0' encoding='ISO-8859-1'?>"
        "<rss><channel><item><title>Amon-Ra St. Brown, café talk</title>"
        "<link>https://e.com/1</link></item></channel></rss>"
    ).encode("latin-1")
    assert rss.parse(raw, "x", "X", 1)[0].title == "Amon-Ra St. Brown, café talk"


# --- Degradation: none of these may raise --------------------------------


def test_truncated_xml_degrades_to_an_empty_list():
    """A publisher's CDN cutting a response mid-document is routine. The
    poller turns [] into a per-source "parsed 0 items" failure; an exception
    here would abort the whole sync instead."""
    cut = ESPN_FEED[: len(ESPN_FEED) // 2]
    assert rss.parse(cut, "espn", "ESPN NFL", 1) == []


def test_assorted_malformed_bodies_degrade_rather_than_raise():
    for junk in (
        "",
        "   ",
        "<rss><channel><item><title>unclosed",
        "<rss><channel><item><title>crossed</item></title></channel></rss>",
        "<html><body>503 Service Unavailable</body></html>",
        '{"items": []}',
        b"\x00\x01\x02 not xml at all",
    ):
        assert rss.parse(junk, "x", "X", 1) == [], f"raised or parsed junk: {junk!r}"


def test_an_empty_channel_yields_an_empty_list():
    """A real feed with no posts: valid XML, zero items. Must be [], not a
    crash and not a phantom item built from the channel's own title/link."""
    xml = (
        "<?xml version='1.0'?><rss version='2.0'><channel>"
        "<title>ESPN.com - NFL</title>"
        "<link>https://www.espn.com/nfl/</link>"
        "<description>Nothing today</description>"
        "</channel></rss>"
    )
    assert rss.parse(xml, "espn", "ESPN NFL", 1) == []


def test_an_atom_feed_with_no_entries_yields_an_empty_list():
    atom = "<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'><title>X</title></feed>"
    assert rss.parse(atom, "x", "X", 1) == []


# --- Dates: absent is None, never invented --------------------------------


def test_an_item_with_no_pubdate_is_kept_with_published_none():
    """Rotowire's blurbs sometimes ship undated. The item is still news, so
    it is kept -- but published stays None rather than being stamped 'now',
    which would date a week-old blurb to this minute."""
    xml = (
        "<rss><channel><item>"
        "<title>Chubb listed as limited</title>"
        "<link>https://e.com/chubb</link>"
        "</item></channel></rss>"
    )
    items = rss.parse(xml, "x", "X", 1)
    assert len(items) == 1
    assert items[0].published is None
    assert items[0].title == "Chubb listed as limited"


def test_an_empty_or_unparseable_pubdate_is_also_none():
    for raw in ("", "   ", "tomorrow-ish", "0000-00-00 00:00:00"):
        xml = (
            f"<rss><channel><item><title>t</title><link>https://e.com/1</link>"
            f"<pubDate>{raw}</pubDate></item></channel></rss>"
        )
        assert rss.parse(xml, "x", "X", 1)[0].published is None, raw


def test_dates_normalise_to_utc_from_both_feed_formats():
    """RFC 822 for RSS, ISO 8601 for Atom, and both offsets and named zones
    in the wild. Everything is stored as UTC so the Houston render is one
    conversion, not two."""
    assert rss.parse_date("Wed, 19 Aug 2026 11:30:00 GMT") == "2026-08-19T11:30:00+00:00"
    assert rss.parse_date("Wed, 19 Aug 2026 06:30:00 -0500") == "2026-08-19T11:30:00+00:00"
    assert rss.parse_date("2026-08-19T11:30:00Z") == "2026-08-19T11:30:00+00:00"
    assert rss.parse_date("2026-08-19T13:30:00+02:00") == "2026-08-19T11:30:00+00:00"
    # Naive ISO: assumed UTC rather than dropped, so the item still sorts.
    assert rss.parse_date("2026-08-19T11:30:00") == "2026-08-19T11:30:00+00:00"


# --- Ids: what dedupe on re-poll is built on ------------------------------


def test_the_id_falls_back_from_guid_to_link_to_title():
    """Feeds omit guid (and Rotowire reuses it). Every fallback must still
    produce an id, or merge() would raise on a KeyError instead of dedupe."""
    base = "<rss><channel><item>{}</item></channel></rss>"
    with_guid = rss.parse(
        base.format("<title>t</title><link>https://e.com/1</link><guid>G-1</guid>"), "x", "X", 1
    )[0]
    link_only = rss.parse(base.format("<title>t</title><link>https://e.com/1</link>"), "x", "X", 1)[
        0
    ]
    title_only = rss.parse(base.format("<title>t</title>"), "x", "X", 1)[0]

    for item in (with_guid, link_only, title_only):
        assert item.id and len(item.id) == 16
    # A guid changes the basis, so it must not collide with the link-only id.
    assert with_guid.id != link_only.id
    assert link_only.id != title_only.id


def test_the_same_story_republished_at_a_new_link_keeps_its_guid_id():
    """Publishers move URLs. guid is preferred precisely so a moved story
    re-polls as the same item instead of badging itself NEW again."""
    base = (
        "<rss><channel><item><title>Same story</title>"
        "<link>{}</link><guid isPermaLink='false'>US-EN-9</guid>"
        "</item></channel></rss>"
    )
    first = rss.parse(base.format("https://e.com/old"), "espn", "ESPN", 1)[0]
    moved = rss.parse(base.format("https://e.com/new"), "espn", "ESPN", 1)[0]
    assert first.id == moved.id


def test_to_dict_carries_the_whole_item():
    """The overlay is JSON; a field missing from the dict is a field the
    browser app never sees, no matter that the dataclass has it."""
    payload = rss.parse(ESPN_FEED, "espn", "ESPN NFL", 1)[0].to_dict()
    assert set(payload) == {
        "id",
        "source_key",
        "source_name",
        "tier",
        "title",
        "summary",
        "link",
        "published",
        "author",
    }
    assert payload["source_key"] == "espn"


# --- the cleaner's escaping order -------------------------------------------
# Found Aug 21. `_clean` stripped tags once and then unescaped twice, so
# anything that *became* a tag on the way out survived the strip.


def test_a_tag_hidden_behind_one_layer_of_escaping_does_not_survive():
    assert rss._clean("Geno Smith &lt;b&gt;out&lt;/b&gt; Sunday") == "Geno Smith out Sunday"


def test_a_script_tag_hidden_behind_two_layers_does_not_survive():
    """The sharp version. "&amp;lt;script&amp;gt;" is not a tag when the
    strip runs and very much is one after two unescapes — and headlines
    reach the page."""
    out = rss._clean("Geno Smith &amp;lt;script&amp;gt;alert(1)&amp;lt;/script&amp;gt;")
    assert "<script" not in out
    assert "</script" not in out
    assert out == "Geno Smith alert(1)"


def test_no_depth_of_nesting_smuggles_a_tag_through():
    """Whatever survives, it must not be markup. Bounded rounds plus a
    final strip, because unbounded unescaping is its own denial of
    service."""
    for layers in range(1, 6):
        raw = "&lt;img src=x onerror=alert(1)&gt;"
        for _ in range(layers - 1):
            raw = raw.replace("&", "&amp;")
        out = rss._clean(f"News {raw}")
        assert "<" not in out and ">" not in out, f"{layers} layers: {out!r}"


def test_ordinary_double_escaped_text_still_decodes():
    """The behaviour the original double-unescape existed for: Yahoo
    ships "Jets&amp;#39; Geno Smith"."""
    assert rss._clean("Jets&amp;#39; Geno Smith") == "Jets' Geno Smith"
    assert rss._clean("Ja&#39;Marr Chase &amp; Tee Higgins") == "Ja'Marr Chase & Tee Higgins"


def test_a_real_tag_is_still_stripped():
    assert rss._clean("<b>Geno Smith</b> out") == "Geno Smith out"


def test_escaped_angle_bracket_prose_survives_the_clean():
    """ "implied &lt;24 but &gt;20 points" is prose, not markup — browsers
    render "<24" as text because a tag open needs a letter, "/", "!" or
    "?". The old any-<...> pattern ate it as a tag, a meaning-changing
    loss the strip/unescape rounds made in the name of safety. Real tags
    still die at any escape depth."""
    assert rss._clean("implied &lt;24 but &gt;20 points") == "implied <24 but >20 points"
    assert rss._clean("a < b and c > d") == "a < b and c > d"
    # The property the rounds exist for is untouched:
    doubled = rss._clean("&amp;lt;script&amp;gt;alert(1)&amp;lt;/script&amp;gt;")
    assert "<script" not in doubled.lower()
    assert rss._clean("<svg/onload=alert(1)>hi") == "hi"
