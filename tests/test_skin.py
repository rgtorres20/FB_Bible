"""The skin every server-rendered page is built from.

`skin.head()` exists because nine pages hand-assembled the same six head
tags and had drifted apart: the alert board carried no favicon at all,
the cheat sheet's empty-board branch dropped the one its full branch had,
and three pages had lost the theme boot and opened in the house navy no
matter which club the user had picked. Centralising that only helps if
the one remaining copy stays complete, so each piece it must emit is
pinned here.

Nothing is mocked -- the module is pure string composition. The two
places it reaches outside itself are checked against the real thing
instead: the asset URLs are fetched through the app (including with the
login gate armed, since /login's artwork has to load for someone who has
no session yet), and the club seed is checked against the real club list.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.feeds import skin, teams

# One page's head, used wherever the arguments are not what is under test.
PAGE = skin.head("cheat sheet", "Cheat sheet")

# Every URL the skin points a browser at.
ASSET_URLS = sorted(set(re.findall(r"(?:href|src)='(/app/[^']+)'", PAGE)))


# --- what head() must never lose again --------------------------------------


@pytest.mark.parametrize(
    "piece",
    [
        "<!doctype html>",
        "<meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        skin.THEME_LINK,
        skin.FAVICON,
        skin.THEME_BOOT,
    ],
)
def test_head_carries_every_piece_the_hand_written_copies_had_dropped(piece):
    """Each of these went missing from at least one of the nine
    hand-written heads. One copy is only an improvement while it is the
    complete one."""
    assert piece in PAGE


def test_head_ends_with_the_way_back():
    """The bar is part of the head so that adding a page cannot produce a
    dead end in the installed PWA, where there is no address bar to fall
    back on."""
    assert PAGE.endswith(skin.home_bar("Cheat sheet"))


def test_head_declares_the_encoding_before_the_title():
    """The title it builds contains an em dash, so a charset that arrived
    after it -- or past the 1024 bytes a browser sniffs -- would render
    the app's own name as mojibake."""
    charset = PAGE.index("<meta charset='utf-8'>")
    assert charset < PAGE.index("<title>")
    assert charset < 1024


def test_head_names_the_page_in_the_title():
    """The tab and the PWA switcher are the only place several of these
    boards are distinguishable from each other."""
    assert "<title>Fantasy Sports Bible — cheat sheet</title>" in PAGE


def test_head_inlines_the_page_stylesheet_it_is_given():
    css = "main{max-width:60ch}"
    assert f"<style>{css}</style>" in skin.head("scorecard", style=css)


def test_head_emits_no_stylesheet_tag_of_its_own_when_given_none():
    """Only the home bar's print rule may bring a <style>; an empty one
    from head() would mean callers cannot tell whether their CSS landed."""
    assert PAGE.count("<style>") == 1
    assert "<style></style>" not in PAGE


def test_head_boot_argument_replaces_the_default_boot():
    """/app/mine serves a seeded boot so a signed-in user's club follows
    them to a new browser. Emitting both would let the unseeded copy run
    second and win."""
    seeded = skin.theme_boot("DAL")
    out = skin.head("my stuff", boot=seeded)
    assert seeded in out
    assert skin.THEME_BOOT not in out
    assert out.count("localStorage.getItem('ww_theme')") == 1


# --- the way back -----------------------------------------------------------


def test_home_bar_links_to_the_app_root_and_shows_the_mark():
    bar = skin.home_bar()
    assert "href='/app/'" in bar
    assert "src='/app/assets/fsb-mark.svg'" in bar


def test_home_bar_names_the_page_it_is_leaving_only_when_told():
    """The label doubles as the "where am I" line on boards that render
    no other chrome, but a bare separator with nothing after it reads as
    a truncation bug."""
    assert "<span>Fantasy Sports Bible · Scorecard</span>" in skin.home_bar("Scorecard")
    assert "<span>Fantasy Sports Bible</span>" in skin.home_bar()
    assert "·" not in skin.home_bar()


def test_home_bar_depends_on_no_page_tokens():
    """Deliberate, per its docstring: these pages do not share a
    stylesheet -- the cheat sheet and the IDP board carry their own -- so
    a bar styled from --color-* variables would be invisible on whichever
    pages did not define them. It inherits instead."""
    bar = skin.home_bar("Alert board")
    assert "var(--" not in bar
    assert "color:inherit" in bar
    assert "currentColor" in bar


def test_home_bar_removes_itself_from_print():
    """The cheat sheet is printed; a nav button on the paper is noise."""
    bar = skin.home_bar()
    assert "@media print{.fsb-home{display:none}}" in bar
    assert "class='fsb-home'" in bar


# --- the assets it points at ------------------------------------------------


def test_the_skin_points_at_the_assets_this_test_knows_about():
    """Guards the two tests below: if the skin grows a new URL they must
    cover it too, rather than silently checking the old three."""
    assert ASSET_URLS == [
        "/app/assets/fsb-icon.svg",
        "/app/assets/fsb-mark.svg",
        "/app/teams.css",
    ]


def test_the_favicon_offers_the_same_icon_to_the_ios_tile():
    """Deliberately one file rather than a second rendering that could
    drift from it."""
    assert "rel='icon' type='image/svg+xml' href='/app/assets/fsb-icon.svg'" in skin.FAVICON
    assert "rel='apple-touch-icon' href='/app/assets/fsb-icon.svg'" in skin.FAVICON
    assert "content='#0B1A36'" in skin.FAVICON


@pytest.mark.parametrize("url", ASSET_URLS)
def test_every_asset_the_skin_names_is_actually_served(url):
    """A renamed file or a dropped route shows up as a missing logo on
    every page at once, and nothing else in the suite fetches these."""
    assert TestClient(main.app).get(url).status_code == 200


@pytest.mark.parametrize("url", ASSET_URLS)
def test_every_asset_stays_public_when_the_login_gate_is_armed(url, monkeypatch):
    """/login is public but lives under /app, and the gate once returned
    401 for its mark, its favicon and its colour tokens -- the page
    looked broken to exactly the people it exists for. Moving an asset
    off the gate's allowlist would bring that back."""
    s = get_settings()
    monkeypatch.setattr(s, "app_auth", True, raising=False)
    monkeypatch.setattr(s, "owner_email", "owner@example.com", raising=False)
    monkeypatch.setattr(s, "app_owner_code", "open-sesame", raising=False)
    monkeypatch.setattr(s, "session_secret", "unit-test-secret", raising=False)
    assert s.app_auth_enabled
    r = TestClient(main.app).get(url, headers={"accept": "text/html"})
    assert r.status_code == 200, f"{url} -> {r.status_code}"


# --- the theme boot ---------------------------------------------------------


def test_the_boot_reads_the_storage_keys_the_app_writes():
    """`ww_theme` and `fb_team` are immutable (CLAUDE.md) and the retired
    mode names are translated rather than reset, so nobody who picked
    Cowboys in August loses Dallas."""
    assert "localStorage.getItem('ww_theme')" in skin.THEME_BOOT
    assert "localStorage.getItem('fb_team')" in skin.THEME_BOOT
    assert "legacy={cowboys:'DAL',titans:'TEN'}" in skin.THEME_BOOT


def test_the_boot_seeds_the_club_a_signed_in_user_saved():
    """The seed is what carries a club to a browser that has never seen
    the app; localStorage still wins, so there is no flash."""
    assert "localStorage.getItem('fb_team')||'DAL'" in skin.theme_boot("DAL")
    assert "localStorage.getItem('fb_team')||'FSB'" in skin.theme_boot(teams.HOUSE)
    # The shared constant is a module global; seeding must not edit it.
    assert "localStorage.getItem('fb_team')||''" in skin.THEME_BOOT


@pytest.mark.parametrize("club", ["", "nope", "dal", "'+alert(1)+'", "DAL'"])
def test_an_unrecognised_club_falls_back_instead_of_reaching_the_script(club):
    """The seed is interpolated into a JS string literal, so the
    allowlist is what stops a stored club from becoming code. Anything
    not a real club must leave the boot byte-identical to the default."""
    assert skin.theme_boot(club) == skin.THEME_BOOT


def test_every_club_can_be_seeded():
    """A club the theme generator serves but the boot refuses would show
    as the house navy on a new device, with nothing to explain why."""
    for club in [*teams.CLUBS, teams.HOUSE]:
        assert f"||'{club}'" in skin.theme_boot(club)


# --- escaping: documented, not endorsed -------------------------------------


def test_head_escapes_the_title_it_is_given():
    """Found latent, Aug 21: `title` was interpolated raw, so it could
    close <title> and open a script. Every call site passed a literal, so
    it was never live -- but one caller passing a league name or a query
    parameter would have made it XSS, and the rest of this codebase
    already escapes league names before putting them in markup."""
    out = skin.head("</title><script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


def test_home_bar_escapes_the_page_label():
    """Same shape, same fix: `here` lands inside a <span>, so a tag in it
    must be text, not markup."""
    bar = skin.home_bar("<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in bar
    assert "&lt;script&gt;" in bar
