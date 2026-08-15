"""Wire stamps for the Out & returning tab.

watched_names() is tested against the real committed index.html on purpose:
the parse exists to track that file, so a design-project sync that changes
the OUTLIST/RETURNING literal shape should fail here, not silently return
zero names in production.
"""

from app.feeds import injury


def test_watched_names_parses_the_real_page():
    names = injury.watched_names()
    assert "Ricky Pearsall" in names  # OUTLIST
    assert "Malik Nabers" in names  # RETURNING
    assert len(names) >= 10


def test_watched_names_has_no_duplicates():
    names = injury.watched_names()
    assert len(names) == len(set(names))


def _mention(name, published, title, source="ESPN", link="https://e/1"):
    return {
        "title": title,
        "published": published,
        "link": link,
        "source_name": source,
        "players": [{"id": "x", "name": name, "position": "TE", "team": "SF"}],
    }


def test_wire_stamps_keep_the_latest_mention():
    items = [
        _mention("George Kittle", "2026-08-14T10:00:00+00:00", "older story"),
        _mention("George Kittle", "2026-08-15T02:00:00+00:00", "newer story"),
    ]
    stamps = injury.wire_stamps(items, ("George Kittle",))
    assert stamps["George Kittle"]["head"] == "newer story"
    assert stamps["George Kittle"]["published"] == "2026-08-15T02:00:00+00:00"


def test_wire_stamps_match_tagged_players_not_headline_text():
    """ "Kittle's backup impressed" tags the backup, not Kittle -- his row
    must not carry someone else's story."""
    item = _mention("Someone Else", "2026-08-15T02:00:00+00:00", "Kittle's backup impressed")
    assert injury.wire_stamps([item], ("George Kittle",)) == {}


def test_wire_stamps_ignore_players_not_on_the_tab():
    item = _mention("Puka Nacua", "2026-08-15T02:00:00+00:00", "practiced fully")
    assert injury.wire_stamps([item], ("George Kittle",)) == {}


def test_wire_stamps_match_names_case_insensitively():
    item = _mention("george kittle", "2026-08-15T02:00:00+00:00", "returned to practice")
    stamps = injury.wire_stamps([item], ("George Kittle",))
    assert stamps["George Kittle"]["head"] == "returned to practice"


def test_wire_stamps_carry_source_and_link_for_the_row():
    item = _mention("George Kittle", "2026-08-15T02:00:00+00:00", "activated", source="CBS")
    stamp = injury.wire_stamps([item], ("George Kittle",))["George Kittle"]
    assert stamp["source"] == "CBS"
    assert stamp["link"] == "https://e/1"
