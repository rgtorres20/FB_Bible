"""Club themes.

Owner request (Aug 21): 32 team themes, picked on first sign-in and
changeable in settings, with the mode switch becoming **My team / Dark /
Light** — and the app opening in the club theme rather than Light.

The contract worth testing is not "the colours are right" (they are brand
facts) but that every generated palette is *legible*. 33 palettes built
by formula is exactly the situation where one club quietly ends up with
grey text on a highlighter, so the thresholds are asserted rather than
eyeballed.
"""

from __future__ import annotations

from app.feeds import teams


def test_there_are_thirty_two_clubs_plus_the_house():
    assert len(teams.CLUBS) == 32
    codes = teams.all_codes()
    assert len(codes) == 33
    assert codes[0] == teams.HOUSE  # "no club yet" leads the list
    assert len(set(codes)) == 33


def test_every_palette_is_legible():
    """Text at AAA against its own ground, accents clearing the UI
    threshold, and button labels readable on the accent they sit on.
    One club failing any of these is a page somebody cannot use."""
    for code in teams.all_codes():
        tokens = teams.palette(*teams.colours(code))
        bg = tokens["--color-bg"]
        assert teams.contrast(bg, tokens["--color-text"]) >= 7.0, code
        assert teams.contrast(bg, tokens["--color-accent"]) >= teams.MIN_ACCENT_CONTRAST, code
        assert teams.contrast(tokens["--color-accent"], tokens["--color-on-accent"]) >= 4.5, code


def test_every_palette_is_a_dark_theme():
    """Club colours are not a palette — half are a dark ground and a
    bright mark, half the reverse. Every theme takes the darker mark as
    its ground so none of them ends up as grey-on-highlighter."""
    for code in teams.all_codes():
        assert teams.luminance(teams.palette(*teams.colours(code))["--color-bg"]) < 0.16, code


def test_a_palette_carries_every_token_the_app_uses():
    """A missing token does not fail loudly — it silently inherits the
    light theme's value into a dark one."""
    reference = set(teams.palette(*teams.colours(teams.HOUSE)))
    assert "--color-bg" in reference and "--color-accent" in reference
    for code in teams.all_codes():
        assert set(teams.palette(*teams.colours(code))) == reference, code


def test_a_clubs_accent_stays_the_clubs_colour_where_it_can():
    """The lift only runs when a mark cannot clear its own ground.
    Kansas City's gold is already fine and must come through untouched."""
    assert teams.palette(*teams.colours("KC"))["--color-accent"] == "#FFB81C"


def test_the_stylesheet_selects_on_both_mode_and_club():
    """Mode and club are independent: switching to Dark and back has to
    return to the club the user picked, not forget it."""
    css = teams.stylesheet()
    assert ':root[data-theme="team"][data-team="DET"]' in css
    assert ':root[data-theme="team"]:not([data-team])' in css  # picked no club
    for code in teams.all_codes():
        assert f'[data-team="{code}"]' in css, code


def test_the_retired_modes_map_onto_real_clubs():
    """Cowboys and Titans modes shipped before clubs existed. Neither
    storage key may be renamed, so a browser still holding one is
    translated rather than reset to the house theme."""
    assert teams.LEGACY_THEMES == {"cowboys": "DAL", "titans": "TEN"}
    for code in teams.LEGACY_THEMES.values():
        assert code in teams.CLUBS


def test_an_unknown_club_falls_back_to_the_house_rather_than_crashing():
    """Stored preferences outlive the code that wrote them."""
    assert teams.colours("XXX") == teams.colours(teams.HOUSE)
    assert teams.name("XXX") == "XXX"
