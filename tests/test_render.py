"""Tests for rendering polled items into the page's feeds.json shape."""

from datetime import UTC, datetime

from app.feeds import render

ITEM = {
    "title": "Nacua expected back at practice next week",
    "summary": "McVay says the psoas soreness is short-term.",
    "source_name": "ESPN NFL",
    "tier": 1,
    "published": "2026-08-14T16:00:00+00:00",
    "link": "https://espn.com/nfl/story/1",
    "players": [{"id": "9493", "name": "Puka Nacua", "position": "WR", "team": "LAR"}],
}

BUNDLED = {
    "updated": "2026-08-14T23:24:32.581Z",
    "note": "Sync-updated feeds.",
    "alerts": [{"name": "Malik Willis", "status": "STARTS TONIGHT"}],
    "news": [{"kind": "Wire", "handle": "Yahoo lineup wire", "text": "Curated item"}],
    "scout": [{"name": "someone"}],
}

NOW = datetime(2026, 8, 15, 6, 0, tzinfo=UTC)


def test_time_renders_central_with_no_zero_padding():
    # 16:00 UTC in August is 11:00 AM CDT.
    assert render.format_time("2026-08-14T16:00:00+00:00") == "Fri Aug 14 · 11:00 AM"


def test_time_handles_midnight_and_noon():
    assert render.format_time("2026-08-14T05:00:00+00:00").endswith("12:00 AM")  # 00:00 CDT
    assert render.format_time("2026-08-14T17:00:00+00:00").endswith("12:00 PM")  # noon CDT


def test_time_is_empty_rather_than_wrong_when_missing_or_bad():
    assert render.format_time(None) == ""
    assert render.format_time("") == ""
    assert render.format_time("not a date") == ""


def test_players_renders_the_committed_string_shape():
    assert render.format_players(ITEM["players"]) == "Puka Nacua · WR · LAR"


def test_players_is_empty_when_nothing_matched():
    assert render.format_players([]) == ""


def test_players_marks_free_agents_rather_than_showing_none():
    out = render.format_players([{"name": "Someone", "position": "RB", "team": None}])
    assert out == "Someone · RB · FA"


def test_news_entry_matches_the_shape_the_page_reads():
    entry = render.to_news_entry(ITEM)

    assert entry["kind"] == "Wire"
    assert entry["handle"] == "ESPN NFL"
    assert entry["trust"] == "Tier 1"
    assert entry["time"] == "Fri Aug 14 · 11:00 AM"
    assert entry["players"] == "Puka Nacua · WR · LAR"
    assert entry["text"].startswith("Nacua expected back")
    assert "McVay" in entry["text"]
    assert entry["link"] == "https://espn.com/nfl/story/1"


def test_entry_does_not_repeat_the_title_when_summary_is_identical():
    entry = render.to_news_entry({**ITEM, "summary": ITEM["title"]})
    assert entry["text"] == ITEM["title"]


def test_entry_survives_a_completely_empty_item():
    entry = render.to_news_entry({})
    assert entry["kind"] == "Wire"
    assert entry["text"] == ""
    assert entry["players"] == ""


def test_merge_puts_live_items_first_and_keeps_curated_ones():
    merged = render.merge_into_feeds(BUNDLED, [ITEM], NOW)

    assert merged["news"][0]["handle"] == "ESPN NFL"
    assert merged["news"][-1]["text"] == "Curated item"


def test_merge_leaves_editorial_feeds_untouched():
    """alerts/scout carry judgements a headline cannot supply. Fabricating
    them would be worse than keeping the curated versions."""
    merged = render.merge_into_feeds(BUNDLED, [ITEM], NOW)

    assert merged["alerts"] == BUNDLED["alerts"]
    assert merged["scout"] == BUNDLED["scout"]


def test_merge_drops_a_curated_item_the_wire_already_carries():
    dupe = {**ITEM, "title": "Curated item", "summary": ""}
    merged = render.merge_into_feeds(BUNDLED, [dupe], NOW)

    assert [n["text"] for n in merged["news"]] == ["Curated item"]


def test_merge_with_nothing_polled_serves_the_committed_file_unchanged():
    """A cold Redis must not blank the app's news tab."""
    assert render.merge_into_feeds(BUNDLED, [], NOW) == BUNDLED


def test_merge_caps_how_many_live_items_reach_the_page():
    many = [{**ITEM, "title": f"story {i}"} for i in range(200)]
    merged = render.merge_into_feeds(BUNDLED, many, NOW)

    assert len(merged["news"]) == render.MAX_LIVE_ITEMS + 1  # + the curated one


def test_merge_does_not_mutate_the_bundled_input():
    before = len(BUNDLED["news"])
    render.merge_into_feeds(BUNDLED, [ITEM], NOW)
    assert len(BUNDLED["news"]) == before


def test_merge_stamps_updated_and_credits_sources():
    merged = render.merge_into_feeds(BUNDLED, [ITEM], NOW)

    assert merged["updated"] == NOW.isoformat()
    assert "Sleeper" in merged["note"]
