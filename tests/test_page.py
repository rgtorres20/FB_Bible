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


# --- the mark, visibly, on the app page (owner, Aug 22) ----------------


def test_the_app_page_shows_the_mark_itself(index_html):
    """The design document carried the artwork only as a `logo.png`
    watermark at `wmOpacity` behind the whole shell — decoration, not
    identity. The owner asked to actually see their logo, so the full
    lockup is injected into the page's own header."""
    served, misses = page.header_mark(index_html)
    assert not misses
    assert "/app/assets/fsb-logo.svg" in served


def test_the_mark_lands_above_the_screen_title(index_html):
    """Not just present somewhere: in `<main>`'s header, ahead of the
    screen kicker and title. That header is the one region every screen
    shares and the only branded spot a phone can see — the sidebar is an
    off-canvas drawer under 769px (mobile.css)."""
    served, _ = page.header_mark(index_html)
    head = served.index("<header")
    assert head < served.index("/app/assets/fsb-logo.svg") < served.index("{{ screenKicker }}")


def test_the_mark_carries_its_own_navy_panel(index_html):
    """docs/BRAND.md, "Rules of use": the wordmark is white and gold, so
    it always sits on navy. On the light theme's cream ground "Fantasy"
    and "Bible" vanish and the name reads as one gold word; across the 32
    club themes it would land on 32 grounds it was never drawn against.

    So the panel's colour must be the literal brand navy and must not be
    a theme token, which is precisely what would follow the theme.
    """
    import re

    served, _ = page.header_mark(index_html)
    # The element wrapping the mark, and nothing else: the last tag opened
    # before the image.
    panel = re.search(r"<div[^>]*>(?=\s*<img src=\"/app/assets/fsb-logo\.svg\")", served)
    assert panel, "the mark is not wrapped in a panel at all"
    assert "background:#0B1A36" in panel.group(0), (
        "the mark sits bare on whichever ground the current theme paints"
    )
    assert "background:var(" not in panel.group(0), (
        "a token ground follows the theme, which is the bug this rule exists for"
    )


def test_the_marks_asset_actually_exists():
    """A transform pointing at a file that is not in the bundle renders a
    broken image and reports no miss — the anchor was found."""
    assert (INDEX.parent / "assets" / "fsb-logo.svg").is_file()


def test_the_mark_survives_the_whole_registry(index_html):
    """The later transforms rewrite the wordmark and the league names by
    literal. `wordmark` replaces the *first* `>FANTASY BIBLE<` only, so an
    injected panel carrying that literal would steal the rename from the
    sidebar and leave it saying the old name."""
    served, _ = page.apply(index_html, page.PRE + page.POST)
    assert served.count("/app/assets/fsb-logo.svg") == 1
    assert ">FANTASY SPORTS BIBLE<" in served


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
    convincing version of the original bug, not a fix.

    The wire and usage groups are honest in the design document itself.
    The board group is corrected at serve time, so it is asserted on the
    served page below rather than here.
    """
    assert '"not wired"' in index_html, "the news wires group must say it is not wired"
    assert '"on/off only"' in index_html, "the usage group must say it is a toggle"


def test_the_board_group_stops_calling_itself_a_list_blend(index_html):
    """Two different things were called sources. The four board sliders
    are hand-written names with no data behind them; they compute one
    ratio that tilts the board between its tier order and live ADP. The
    real ranking lists blend with no weights at all.

    So the panel's old note -- "Each list's share blends into Draft
    analyzer order" -- described code deleted on Aug 21. A real control
    with a wrong label is worse than a dead one: a dead control teaches
    you to stop touching it.
    """
    served, misses = page.source_truth(index_html)
    assert not misses
    assert "Rank lists — draft board" not in served
    assert "Each list's share blends" not in served
    assert "Board order mix" in served
    assert "how far the draft board leans on live ADP versus your own tier order" in served
    # And it points at where the real lists actually live.
    assert "/app/mine" in served


def test_the_analyzer_slider_stops_promising_named_sources(index_html):
    """Its caption read "100 = pure ESPN/Yahoo ADP blend", which names two
    lists it does not consult. It mixes tier order against live ADP."""
    served, _ = page.source_truth(index_html)
    assert "pure ESPN/Yahoo ADP blend" not in served
    assert "0 = your own tier order · 100 = live ADP" in served
    assert "Board order</span>" in served, "the label mobile.js anchors the panel on"


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
