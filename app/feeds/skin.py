"""The app's skin, shared by every server-rendered interactive page.

One source for the design tokens (mirrored from the served page's own
[data-skin]/[data-theme] blocks and mobile.css's Titans set) and for the
theme boot script that reads the page's `ww_theme` localStorage before
first paint -- so /app/mock, /login and /app/access all open in whatever
mode the app itself is in.
"""

from __future__ import annotations

import html as html_mod

from . import teams

TOKENS_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;800;900&display=swap');
:root {
  --color-bg: oklch(0.955 0.025 90); --color-text: oklch(0.25 0.06 260);
  --color-neutral-200: oklch(0.92 0.025 90); --color-neutral-300: oklch(0.86 0.025 90);
  --color-neutral-400: oklch(0.72 0.03 95); --color-neutral-600: oklch(0.5 0.05 255);
  --color-neutral-700: oklch(0.42 0.06 258); --color-neutral-800: oklch(0.32 0.06 260);
  --color-accent: #b22234; --color-accent-100: oklch(0.92 0.03 20);
  --color-accent-200: oklch(0.85 0.06 20); --color-accent-400: oklch(0.55 0.15 20);
  --color-accent-700: oklch(0.44 0.15 18); --color-accent-800: oklch(0.35 0.12 18);
}
:root[data-theme="cowboys"] {
  --color-bg: oklch(0.14 0.015 260); --color-text: oklch(0.95 0.01 90);
  --color-neutral-200: oklch(0.18 0.008 260); --color-neutral-300: oklch(0.24 0.01 260);
  --color-neutral-400: oklch(0.4 0.015 260); --color-neutral-600: oklch(0.66 0.015 255);
  --color-neutral-700: oklch(0.75 0.012 250); --color-neutral-800: oklch(0.86 0.008 220);
  --color-accent: oklch(0.62 0.16 20); --color-accent-100: oklch(0.26 0.06 20);
  --color-accent-200: oklch(0.33 0.09 20); --color-accent-400: oklch(0.55 0.14 20);
  --color-accent-700: oklch(0.74 0.14 20); --color-accent-800: oklch(0.84 0.1 22);
}
:root[data-theme="titans"] {
  --color-bg: oklch(0.17 0.04 255); --color-text: oklch(0.94 0.008 240);
  --color-neutral-200: oklch(0.21 0.035 255); --color-neutral-300: oklch(0.26 0.04 255);
  --color-neutral-400: oklch(0.42 0.045 252); --color-neutral-600: oklch(0.66 0.04 248);
  --color-neutral-700: oklch(0.75 0.035 245); --color-neutral-800: oklch(0.86 0.02 240);
  --color-accent: oklch(0.68 0.12 245); --color-accent-100: oklch(0.27 0.06 250);
  --color-accent-200: oklch(0.34 0.08 248); --color-accent-400: oklch(0.56 0.11 246);
  --color-accent-700: oklch(0.76 0.11 242); --color-accent-800: oklch(0.85 0.08 240);
}
:root[data-theme="dark"] {
  --color-bg: #000; --color-text: oklch(0.95 0.01 90);
  --color-neutral-200: oklch(0.18 0.008 260); --color-neutral-300: oklch(0.24 0.01 260);
  --color-neutral-400: oklch(0.4 0.015 260); --color-neutral-600: oklch(0.66 0.015 255);
  --color-neutral-700: oklch(0.75 0.012 250); --color-neutral-800: oklch(0.86 0.008 220);
  --color-accent: oklch(0.62 0.16 20); --color-accent-100: oklch(0.26 0.06 20);
  --color-accent-200: oklch(0.33 0.09 20); --color-accent-400: oklch(0.55 0.14 20);
  --color-accent-700: oklch(0.74 0.14 20); --color-accent-800: oklch(0.84 0.1 22);
}
* { box-sizing: border-box; }
body { font-family: 'Archivo', system-ui, sans-serif; margin: 18px;
       color: var(--color-text); background: var(--color-bg);
       font-size: 14px; line-height: 1.45; }
"""

# The stylesheet holding all 33 team palettes, linked rather than inlined
# so a browser fetches it once for every page in the app.
THEME_LINK = "<link rel='stylesheet' href='/app/teams.css'>"

# Applied before first paint so pages never flash the wrong mode.
#
# Three modes now (owner, Aug 21): the user's club, Dark, Light -- and
# the app opens in the club theme rather than Light, which for someone
# who has not picked one is the house navy. `light` is the bare :root
# palette, so it is the one mode that sets no attribute at all.
#
# Neither storage key may be renamed (CLAUDE.md), so the pre-club values
# are translated instead of dropped: whoever picked Cowboys mode in
# August still gets Dallas.
THEME_BOOT = (
    "<script>try{"
    "var t=localStorage.getItem('ww_theme')||'team';"
    "var club=localStorage.getItem('fb_team')||'';"
    "var legacy={cowboys:'DAL',titans:'TEN'};"
    "if(legacy[t]){club=club||legacy[t];t='team';}"
    "if(['team','dark','light'].indexOf(t)<0)t='team';"
    "if(t!=='light')document.documentElement.dataset.theme=t;"
    "if(t==='team'&&club)document.documentElement.dataset.team=club;"
    "}catch(e){}</script>"
)


def theme_boot(club: str = "") -> str:
    """The boot script, optionally seeded with the club this signed-in
    user saved.

    The seed is what makes a club follow someone to a new device: the
    theme still renders from localStorage so there is no flash, but on a
    browser that has never seen this app the stored choice fills in
    instead of falling back to the house navy.
    """
    seed = club if club in {*teams.CLUBS, teams.HOUSE} else ""
    return THEME_BOOT.replace(
        "localStorage.getItem('fb_team')||''",
        f"localStorage.getItem('fb_team')||'{seed}'",
        1,
    )


# Every page this app serves points at the same icon. SVG favicons are
# supported everywhere the rest of this app needs (Safari 15+, Firefox,
# Chromium); the apple-touch-icon line is what an iOS home-screen tile
# reads, and it is deliberately the same file rather than a second
# rendering that could drift from it.
FAVICON = (
    THEME_LINK + "<link rel='icon' type='image/svg+xml' href='/app/assets/fsb-icon.svg'>"
    "<link rel='apple-touch-icon' href='/app/assets/fsb-icon.svg'>"
    "<meta name='theme-color' content='#0B1A36'>"
)


# Every page this app serves as a full document, and therefore every page
# that needs a way home. Installed as a PWA there is no address bar, so a
# page whose only exit is a text link is a dead end -- the owner hit
# exactly that after picking a club theme (Aug 21).
#
# Canonical, and read rather than copied: `tests/test_navigation.py` walks
# it signed in and signed out, `scripts/verify_live.py` walks it against
# the deployment, and `scripts/lint_docs.py` holds CLAUDE.md to it. It was
# duplicated in the first two, and it drifted the first time a page was
# added -- /app/scoring reached the unit test's copy and not the live one.
SERVED_PAGES: tuple[str, ...] = (
    "/app/mine",
    "/app/leagues",
    "/app/mock",
    "/app/mock/board",
    "/app/nextup",
    "/app/scorecard",
    "/app/idp",
    "/app/scoring",
    "/app/cheatsheet",
    "/app/alerts300",
    # Owner-only, and missed by the first pass of this list -- the docs
    # lint found it served as a full page with no way back (Aug 21).
    "/app/access",
)


# Of those, the ones only the owner may open. They still render a home
# bar -- `tests/test_navigation.py` proves it, signed in and signed out --
# but a watchdog cannot check that, because a watchdog is not the owner:
# the route bounces it to /login, and asserting a home bar on the sign-in
# page fails for a page that is working correctly. What the watchdog can
# verify is that it bounces at all, which is the more important claim.
# A plain literal on purpose: `scripts/verify_live.py` reads this file
# with `ast.literal_eval`, which cannot evaluate a `frozenset(...)`
# call. Same reason SERVED_PAGES is a bare tuple.
OWNER_ONLY: tuple[str, ...] = ("/app/access",)


def home_bar(here: str = "") -> str:
    """A way back to the app, on every page this server renders.

    Owner, Aug 21: after picking a team on /app/mine there was no way
    back to the homepage. The link existed there, buried mid-sentence in
    a paragraph of 12px grey text — and on six other pages (the mock
    room, the boards, the cheat sheet, next-man-up, the scorecard) there
    was no way back at all. In the installed PWA there is no address bar
    and no browser chrome either, so a missed text link is a dead end
    with no exit.

    Deliberately self-contained: styles are inline and the print rule
    rides in its own tag, because these pages do not share one
    stylesheet — the cheat sheet and the IDP board carry their own — and
    a nav that only works on half of them is the bug again.
    """
    # Escaped: `here` is the page's own name today, but an unescaped
    # interpolation point is one caller away from being XSS, and the
    # rest of this codebase already escapes league names before
    # putting them in markup.
    label = f" · {html_mod.escape(here)}" if here else ""
    return (
        "<style>@media print{.fsb-home{display:none}}</style>"
        "<a class='fsb-home' href='/app/' style=\"display:inline-flex;"
        "align-items:center;gap:8px;margin:0 0 14px;padding:6px 10px 6px 8px;"
        "font-family:'Archivo',system-ui,sans-serif;font-size:11px;"
        "font-weight:800;letter-spacing:0.08em;text-transform:uppercase;"
        "text-decoration:none;color:inherit;border:2px solid currentColor;"
        'border-radius:0">'
        "<span aria-hidden='true'>&#8592;</span>"
        "<img src='/app/assets/fsb-mark.svg' alt='' width='26' height='20' "
        "style='display:block'>"
        f"<span>Fantasy Sports Bible{label}</span></a>"
    )


def head(title: str, here: str = "", style: str = "", boot: str = "") -> str:
    """The whole top of a served page: head tags, then the way back.

    Owner, Aug 21: "my fab logo should be on all pages." It was not.
    Every page hand-assembled its own head, so each one could miss a
    piece independently -- and they had drifted: the alert board carried
    no favicon at all, the cheat sheet's empty-board branch dropped the
    one its full branch had, and three pages had lost the theme boot, so
    they rendered in the house navy no matter which club the user picked.

    The same lesson as the home bar. Nine hand-written copies of the same
    six lines is nine chances to forget one, so there is now one copy.
    Pass the page's own stylesheet as `style`; it is inlined in place.
    """
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>Fantasy Sports Bible — {html_mod.escape(title)}</title>"
        + FAVICON
        + (f"<style>{style}</style>" if style else "")
        + (boot or THEME_BOOT)
        + home_bar(here)
    )
