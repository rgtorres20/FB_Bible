"""The hand-read lists carry an honest date, and cannot drift off it.

Owner, Aug 25: "we need to add dates so i know if this is latest or
preseason". Two tabs on the app page are constants no feed touches --
Sleepers (TARGETS) and Backup RBs (CUFFS) -- and neither said anything
about its own age while both had stood since Aug 14, through a round of
preseason games.

A stamp somebody has to remember to update is the same bug as the frozen
"Today" timestamps this repo already fixed: true when written, quietly
rotting after. So the date is pinned to a digest of the content, and the
first test here is the one that matters.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.feeds import curated

INDEX = Path("frontend/index.html").read_text(encoding="utf-8")
TODAY = date(2026, 8, 25)


@pytest.mark.parametrize("name", sorted(curated.CURATED))
def test_the_date_cannot_drift_off_the_content(name):
    """Edit a list without moving its as-of date and this fails, naming
    it. That is the whole design: a date nobody is forced to update is a
    date that starts true and goes quietly wrong."""
    live = curated.digest(INDEX, name)

    assert live, f"{name} is no longer in the page under that name"
    assert live == curated.CURATED[name]["sha"], (
        f"{name} changed but its as_of date did not. Update BOTH in "
        f"app/feeds/curated.py -- new sha is {live}"
    )


@pytest.mark.parametrize("name", sorted(curated.CURATED))
def test_every_stamped_list_is_actually_on_the_page(name):
    assert curated.block(INDEX, name), name


def test_both_tabs_get_stamped():
    served, n = curated.inject(INDEX, TODAY)

    assert n == 2
    assert served.count("Read by hand") == 2


def test_the_stamp_says_the_date_and_the_age():
    """A date alone makes the reader do arithmetic; an age alone hides
    which week it was. Both, or the stamp does not answer the question
    that was asked."""
    line = curated.stamp("TARGETS", TODAY)

    assert "Aug 14, 2026" in line
    assert "11 days ago" in line


def test_it_calls_itself_read_by_hand():
    """Not "curated", not a source name that would read as a feed. The
    point of this stamp is that the reader can distrust it."""
    assert curated.stamp("CUFFS", TODAY).startswith("Read by hand")


def test_the_backup_table_now_says_its_usage_is_measured():
    """This test used to assert the opposite, and the change is the point.

    CUFFS carried "78% rush · 22% routes" and "24 GL carries" with no
    source behind any of them. depth.inject_cuffs replaces those with
    Sleeper's real '25 numbers, so the stamp stops calling them estimates
    -- and now says which half is which, because the picks around them
    are still somebody's judgement and still carry a hand-read date."""
    served, _ = curated.inject(INDEX, TODAY)

    stamp = curated.stamp("CUFFS", TODAY)
    entry = curated.CURATED["CUFFS"]

    assert "usage measured from Sleeper '25" in served
    assert "the picks are judgement" in served
    # Scoped to this tab's own line. Other surfaces on the page -- run
    # edges, week review, FFBets salaries -- ARE estimates and say so
    # correctly, so a page-wide search would fail on their honesty.
    assert "estimates" not in str(entry["source"])
    assert stamp.startswith("Read by hand")


def test_age_words_reads_naturally_at_the_edges():
    assert curated.age_words(TODAY, TODAY) == "today"
    assert curated.age_words(date(2026, 8, 24), TODAY) == "yesterday"
    assert curated.age_words(date(2026, 7, 25), TODAY) == "31 days ago"
    # A date in the future is a mistake, not a negative age.
    assert curated.age_words(date(2026, 9, 1), TODAY) == "today"


def test_a_missing_anchor_stamps_what_it_can_and_reports_it():
    """Same rule as every other injection: a tab whose anchor moved goes
    unstamped rather than taking the other tab's date."""
    broken = INDEX.replace('{{ isCuffs }}" hint-placeholder-val="{{ false }}">', "<!-- gone -->", 1)

    served, n = curated.inject(broken, TODAY)

    assert n == 1
    assert served.count("Read by hand") == 1
