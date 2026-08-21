"""Every serve-time transform actually fires against the real page.

These used to be fifteen inline `html.replace()` calls in main.py. A
replace whose anchor is missing returns the html unchanged and reports
nothing — the page still serves, missing a feature, and looks fine. That
is the same failure as a control wired to nothing: you cannot tell
"working" from "not running at all", which is the bug class this repo
keeps paying for.

So the load-bearing test here is the first one: every transform, run
against the committed `frontend/index.html`, must find every anchor it
looks for. A design-project resync that renames a literal fails here
instead of silently dropping a feature in production.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.feeds import page

INDEX = Path(__file__).resolve().parents[1] / "frontend" / "index.html"

ALL_TRANSFORMS = page.PRE + page.POST + (page.stage_badge,)


@pytest.fixture(scope="module")
def index_html() -> str:
    return INDEX.read_text(encoding="utf-8")


@pytest.mark.parametrize("transform", ALL_TRANSFORMS, ids=lambda t: t.__name__)
def test_every_transform_finds_its_anchors_in_the_real_page(transform, index_html):
    """The regression guard. A renamed literal in the design document is
    caught here rather than in production, where the only symptom is a
    feature quietly not being there."""
    _, misses = transform(index_html)
    assert misses == [], f"{transform.__name__} found no anchor for: {misses}"


@pytest.mark.parametrize("transform", ALL_TRANSFORMS, ids=lambda t: t.__name__)
def test_every_transform_reports_a_miss_rather_than_passing_silently(transform):
    """The other half: given a page with none of its anchors, a transform
    must say so. A transform that returns no misses on empty input cannot
    ever warn us, which would make the test above meaningless."""
    html, misses = transform("nothing here matches any anchor")
    assert misses, f"{transform.__name__} silently did nothing"
    assert html == "nothing here matches any anchor"


def test_apply_collects_misses_across_the_registry():
    html, misses = page.apply("<html></html>", page.PRE)
    assert len(misses) >= len(page.PRE), "apply() dropped misses on the floor"
    assert html == "<html></html>"


def test_head_tags_compounds_if_applied_twice(index_html):
    """Deliberately documented, not fixed. `head_tags` inserts before
    `</head>` and leaves `</head>` in place, so running it on an already
    transformed page injects a second copy.

    That is fine because `main.py` reads `frontend/index.html` from disk on
    every request and transforms the fresh copy — but it means the
    transformed html must never be cached and re-fed through the registry.
    This test is the tripwire for anyone who tries."""
    once, _ = page.head_tags(index_html)
    twice, _ = page.head_tags(once)
    assert twice.count('href="mobile.css"') == 2
    assert once.count('href="mobile.css"') == 1


def test_head_carries_the_mark_and_the_theme_boot(index_html):
    """docs/BRAND.md: the favicon and club boot are injected rather than
    committed, so a resync cannot drop the brand or leave the page on the
    wrong club."""
    html, _ = page.head_tags(index_html)
    assert "/app/assets/fsb-icon.svg" in html
    assert "ww_theme" in html
    assert 'href="mobile.css"' in html


def test_retired_theme_names_are_translated_not_reset(index_html):
    """A browser still holding `cowboys` or `titans` must be translated by
    the boot, never reset to the default — those are immutable storage
    keys (CLAUDE.md)."""
    html, _ = page.mode_picker(index_html)
    assert 'th === "cowboys"' in html and 'th === "titans"' in html
    assert 'th === "team"' in html


def test_the_page_opens_on_the_club_theme(index_html):
    """Owner, Aug 21: "home page should be the dark blue not light mode"."""
    html, _ = page.mode_picker(index_html)
    assert 'theme: "team"' in html


def test_league_names_leave_no_design_document_names_behind(index_html):
    """The picker values and the code comparing against them have to move
    together, or the board filters against a league nobody can select."""
    html, _ = page.league_names(index_html)
    for stale in ("Sunday Gravy", "The Trenches", "Gravy", "Trenches"):
        assert stale not in html, f"{stale!r} survived the rename"


def test_beta_badge_is_not_applied_by_default(index_html):
    """stage_badge is called only for the preview stage; prod and local
    runs must serve no badge at all (docs/ENVIRONMENTS.md)."""
    html, _ = page.apply(index_html, page.PRE + page.POST)
    assert "fb-stage-badge" not in html


# --- the Trusted-sources panel's honesty (design resync, Aug 21) --------
# Fable's redesign closed the false-positive defect on the client: the
# sliders that fed nothing are gone, and each group states what it does.
# These assertions are against the design document rather than a
# transform, because the property is the panel's honesty and a resync is
# exactly what would silently undo it.


def test_only_the_rank_lists_get_a_slider(index_html):
    """Five of nine sliders used to move a bar and change no output. The
    board group is the only one whose weights reach the draft blend, so
    it is the only group that may render a slider."""
    assert "showSlider: board && on" in index_html


def test_each_source_group_states_what_it_actually_does(index_html):
    """A grouped panel that still implied influence would be a more
    convincing version of the original bug, not a fix."""
    assert '"not wired"' in index_html, "the news wires group must say it is not wired"
    assert '"on/off only"' in index_html, "the usage group must say it is a toggle"
    assert '" in blend"' in index_html, "the board group must say how many lists count"


def test_every_source_declares_its_group(index_html):
    """An ungrouped source would render outside all three headings and
    inherit no honesty label at all."""
    import re

    block = re.search(r"const SOURCES = \[(.*?)\n\];", index_html, re.S)
    assert block, "SOURCES array not found — the panel was restructured"
    rows = [r for r in block.group(1).splitlines() if r.strip().startswith("{")]
    assert rows, "no sources parsed"
    ungrouped = [r.strip()[:60] for r in rows if "group:" not in r]
    assert not ungrouped, f"sources with no group: {ungrouped}"
