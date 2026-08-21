"""The scorecard page — and the numbers it refuses to print.

The whole value of this page is negative space. Anything can render a
percentage; what makes a scorecard evidence is that it will not show one
it cannot back. So the assertions here are mostly about absence:

  * **An empty ledger prints no rate.** Not 0%, not "—%", not a
    placeholder tile. 0% reads as "the app is always wrong", and a
    placeholder reads as a measurement. The page says which games it is
    waiting for instead.
  * **Only settled calls reach the rate.** A push is not a win and an
    unplayed game is not a miss; folding either in is the exact false
    positive the page exists to catch, and it would flatter the number
    silently.
  * **Calibration, not just the rate.** "Said 78, hit 33" is the finding.
    A bare 33% hides that the app was loudly confident about it.
  * **Prose stays unscored.** Capsules, verdicts, mover reads and
    previews are named as unscored rather than graded against a rubric
    invented to make coverage look complete.

Ledgers here are built through `scorecard.record()` and
`scorecard.grade()` rather than hand-written dicts, so the fixtures
cannot quietly diverge from the shape the store actually holds.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from app.feeds import accuracy, scorecard

# Evening in Houston, next day in UTC -- a stamp rendered in UTC would
# print tomorrow's date.
NOW = datetime(2026, 9, 15, 2, 30, tzinfo=UTC)
CENTRAL_STAMP = "Mon Sep 14, 09:30 PM Central"

SEASON, WEEK = 2026, 2
NAMES = {"josh allen": "a", "derrick henry": "b", "patrick mahomes": "c"}

# Any percentage at all, so a new placeholder tile cannot slip past a
# test that only looked for the literal "0%".
ANY_PCT = re.compile(r"\d+\s*%")


def _pred(name: str, prop: str, line: str, lean: str, conf: int) -> dict:
    return {
        "name": name,
        "meta": "QB · BUF",
        "prop": prop,
        "line": line,
        "lean": lean,
        "conf": conf,
    }


def _preds() -> list[dict]:
    return [
        _pred("Josh Allen", "Passing TDs", "1.5", "OVER", 78),
        _pred("Derrick Henry", "Rushing TDs", "0.5", "OVER", 74),
        _pred("Patrick Mahomes", "Passing TDs", "1.5", "UNDER", 58),
    ]


def _ledger(preds: list[dict] | None = None, box: dict | None = None) -> dict:
    ledger, _ = scorecard.record(None, preds or _preds(), SEASON, WEEK, "2026-09-13T12:00:00Z")
    if box:
        ledger, _ = scorecard.grade(ledger, box, NAMES, SEASON, WEEK)
    return ledger


def _body(page: str) -> str:
    """Everything below the head. The stylesheet is full of percentages
    and would drown any assertion about numbers on the page."""
    return page.split("<main>", 1)[1]


# --- the refusal ------------------------------------------------------------


@pytest.mark.parametrize("ledger", [None, {}, scorecard.blank()], ids=["none", "empty", "blank"])
def test_an_empty_ledger_prints_no_rate_of_any_kind(ledger):
    """The core promise. Nothing has been recorded, so there is nothing
    to be right about, and the page must not print a number that looks
    like it measured something."""
    page = accuracy.build_html(ledger, {"week_label": "Preseason Week 3"}, NOW)
    assert "Nothing recorded yet" in page
    assert ANY_PCT.search(_body(page)) is None, "a page with no evidence printed a percentage"
    assert "hit rate" not in page.lower()
    assert "record</div>" not in page  # no big-number tiles at all


def test_the_empty_page_names_what_it_is_waiting_for():
    """ "Nothing recorded" with no reason is indistinguishable from a
    broken sync. The reason from `current_week` says which it is."""
    page = accuracy.build_html(None, {"week_label": "Preseason Week 3"}, NOW)
    assert "preseason" in page.lower()
    assert accuracy.build_html(None, None, NOW).count("no scoreboard pushed yet") == 1


def test_recorded_but_ungraded_calls_still_print_no_rate():
    """The second empty state, and the more dangerous one: three calls
    are on the record, so there is something to count -- and counting it
    before the games are played would be an accuracy figure over zero
    results."""
    page = accuracy.build_html(_ledger(), {"week_label": "Week 2"}, NOW)
    assert "Nothing graded yet" in page
    assert "3</b> calls are" in page
    assert ANY_PCT.search(_body(page)) is None
    assert "no accuracy figure here until there are games behind it" in page


def test_one_open_call_is_counted_in_the_singular():
    page = accuracy.build_html(
        _ledger([_pred("Josh Allen", "Passing TDs", "1.5", "OVER", 78)]),
        {"week_label": "Week 2"},
        NOW,
    )
    assert "1</b> call is" in page


# --- what reaches the rate --------------------------------------------------


def test_a_push_is_excluded_from_the_rate_rather_than_counted_a_win():
    """Allen hits, Henry misses, Mahomes pushes on a whole-number line.
    The honest rate is 1 of 2. A push folded in as a win would read 67%."""
    box = {"a": {"pass_td": 3}, "b": {"rush_td": 0}, "c": {"pass_td": 2}}
    preds = [
        _pred("Josh Allen", "Passing TDs", "1.5", "OVER", 78),
        _pred("Derrick Henry", "Rushing TDs", "0.5", "OVER", 74),
        _pred("Patrick Mahomes", "Passing TDs", "2", "UNDER", 58),
    ]
    page = accuracy.build_html(_ledger(preds, box), {"week_label": "Week 3"}, NOW)
    assert "50%" in page
    assert "67%" not in page, "a push was counted as a win"
    assert "1–1" in page  # record: one hit, one miss, the push in neither
    assert "pushed" in page  # and it is reported, not hidden


def test_an_unplayed_game_is_excluded_rather_than_scored_a_miss():
    """Only Allen's box score exists. Henry and Mahomes did not appear,
    which is not a wrong call about what they would have done -- 100% of
    1 is the truth, 33% of 3 is a punishment for an injury."""
    page = accuracy.build_html(_ledger(box={"a": {"pass_td": 3}}), {"week_label": "Week 3"}, NOW)
    assert "100%" in page
    assert "33%" not in page
    assert "awaiting result" in page


# --- calibration ------------------------------------------------------------


def test_the_page_reports_the_band_it_claimed_against_what_happened():
    """The finding a bare hit rate hides: three calls made at 78%
    confidence, one right. The row has to carry both numbers and the gap
    between them, or the confidence figure is decoration."""
    preds = [_pred(f"P{i}", "Passing TDs", "1.5", "OVER", 78) for i in range(3)]
    box = {"p0": {"pass_td": 3}, "p1": {"pass_td": 0}, "p2": {"pass_td": 1}}
    ledger = _ledger(preds, None)
    ledger, _ = scorecard.grade(ledger, box, {f"p{i}": f"p{i}" for i in range(3)}, SEASON, WEEK)

    page = accuracy.build_html(ledger, {"week_label": "Week 3"}, NOW)
    assert "Calibration" in page
    row = next(line for line in page.split("<tr>") if "70–79%" in line)
    assert "<td class='n'>3</td>" in row  # calls in the band
    assert "<td class='n'>78%</td>" in row  # what it said
    assert "<td class='n'><b>33%</b></td>" in row  # what happened
    assert "<td class='n'>-45</td>" in row  # and the gap, signed


def test_empty_confidence_bands_are_left_out_rather_than_shown_as_zero():
    """A band with no calls in it has no rate. Printing 0% for it would
    invent three findings out of one."""
    box = {"a": {"pass_td": 3}, "b": {"rush_td": 1}, "c": {"pass_td": 1}}
    page = accuracy.build_html(_ledger(box=box), {"week_label": "Week 3"}, NOW)
    assert "80–100%" not in page, "an empty band was rendered"
    assert "70–79%" in page and "50–59%" in page


def test_the_by_prop_table_splits_the_record_by_what_was_claimed():
    box = {"a": {"pass_td": 3}, "b": {"rush_td": 0}, "c": {"pass_td": 1}}
    page = accuracy.build_html(_ledger(box=box), {"week_label": "Week 3"}, NOW)
    assert "By prop" in page
    passing = next(line for line in page.split("<tr>") if "Passing TDs" in line)
    assert "<td class='n'>2</td><td class='n'>2</td><td class='n'><b>100%</b></td>" in passing
    rushing = next(line for line in page.split("<tr>") if "Rushing TDs" in line)
    assert "<td class='n'>1</td><td class='n'>0</td><td class='n'><b>0%</b></td>" in rushing


# --- what is deliberately not scored ---------------------------------------


GRADED = (_ledger(box={"a": {"pass_td": 3}}), {"week_label": "Week 3"})
OPEN = (_ledger(), {"week_label": "Week 2"})
BARE = (None, {"week_label": "Preseason Week 3"})

STATES = pytest.mark.parametrize(
    "state", [BARE, OPEN, GRADED], ids=["nothing-recorded", "nothing-graded", "graded"]
)


@STATES
def test_prose_surfaces_are_named_and_left_unscored(state):
    """Capsules, verdicts, mover reads and previews are prose. Scoring
    them would need an invented rubric and would produce a number that
    looks measured. The page says they are unscored rather than letting
    a reader assume the rate covers everything the app says."""
    page = accuracy.build_html(*state, NOW)
    assert "unscored" in page
    for surface in ("capsules", "wire verdicts", "mover reads", "matchup previews"):
        assert surface in page, surface
    assert "Only falsifiable calls are counted" in page


@STATES
def test_every_state_says_the_record_is_written_before_the_games(state):
    """The immutability claim is what makes the page evidence rather than
    opinion, so it cannot live only on the branch that has numbers."""
    page = accuracy.build_html(*state, NOW)
    assert "written before the games and never edited after" in page


# --- the head ---------------------------------------------------------------


@STATES
def test_every_state_carries_the_tab_icon_and_the_mark(state):
    """Three separate returns from one function; the cheat sheet's two
    branches had already drifted apart on exactly this."""
    page = accuracy.build_html(*state, NOW)
    assert "/app/assets/fsb-icon.svg" in page, "no tab icon"
    assert "/app/assets/fsb-mark.svg" in page, "the mark is missing"


@STATES
def test_every_state_has_a_way_back_to_the_app(state):
    page = accuracy.build_html(*state, NOW)
    assert "class='fsb-home' href='/app/'" in page
    assert "Fantasy Sports Bible · Scorecard" in page


@STATES
def test_every_state_stamps_the_check_in_houston_time(state):
    """America/Chicago. 02:30 UTC is the previous evening there, so a UTC
    stamp would print the wrong day as well as the wrong hour."""
    page = accuracy.build_html(*state, NOW)
    assert f"checked {CENTRAL_STAMP}" in page
