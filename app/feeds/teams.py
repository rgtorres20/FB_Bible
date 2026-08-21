"""The 32 clubs, as themes.

Owner request (Aug 21): "add 32 themes based on team picks so when a new
user logs in they select their favourite team and that background is
added to Theme", with the mode picker becoming **their team / Dark /
Light**, and the team settable in settings.

Two design decisions worth stating, because both constrain what a theme
can look like:

  * **Every team theme is a dark theme.** Club colours are not a palette
    -- half of them are a dark ground and a bright mark, the other half
    the reverse, and a few (Miami's aqua, Green Bay's gold) are bright
    enough that using them as a page ground would put grey text on a
    highlighter. So each theme takes the *darker* of the club's two
    colours as its ground and the *brighter* one as its accent. Every
    theme is legible by construction, and still unmistakably the club's.
  * **The shades are computed here, not in CSS.** `color-mix()` would be
    shorter, but this way the whole palette is plain hex, deterministic,
    and testable -- the contrast check in the tests is a real assertion
    rather than a hope about what a browser will produce.

The house theme (`FSB`) is the app's own navy and gold, and is what a
signed-in user sees before they pick a club. It is also the default the
app opens in: the owner's call, Aug 21 -- "home page should be the dark
blue not light mode".

Colours are the clubs' published primary and secondary marks, curated
Aug 21 2026. They are brand facts rather than a live feed; no endpoint
serves them, and they change roughly never.
"""

from __future__ import annotations

HOUSE = "FSB"

# code -> (display name, darker mark, brighter mark)
CLUBS: dict[str, tuple[str, str, str]] = {
    "ARI": ("Cardinals", "#97233F", "#FFB612"),
    "ATL": ("Falcons", "#000000", "#A71930"),
    "BAL": ("Ravens", "#241773", "#9E7C0C"),
    "BUF": ("Bills", "#00338D", "#C60C30"),
    "CAR": ("Panthers", "#101820", "#0085CA"),
    "CHI": ("Bears", "#0B162A", "#C83803"),
    "CIN": ("Bengals", "#000000", "#FB4F14"),
    "CLE": ("Browns", "#311D00", "#FF3C00"),
    "DAL": ("Cowboys", "#041E42", "#869397"),
    "DEN": ("Broncos", "#002244", "#FB4F14"),
    "DET": ("Lions", "#0076B6", "#B0B7BC"),
    "GB": ("Packers", "#203731", "#FFB612"),
    "HOU": ("Texans", "#03202F", "#A71930"),
    "IND": ("Colts", "#002C5F", "#A2AAAD"),
    "JAX": ("Jaguars", "#101820", "#D7A22A"),
    "KC": ("Chiefs", "#E31837", "#FFB81C"),
    "LAC": ("Chargers", "#0080C6", "#FFC20E"),
    "LAR": ("Rams", "#003594", "#FFA300"),
    "LV": ("Raiders", "#000000", "#A5ACAF"),
    "MIA": ("Dolphins", "#005778", "#008E97"),
    "MIN": ("Vikings", "#4F2683", "#FFC62F"),
    "NE": ("Patriots", "#002244", "#C60C30"),
    "NO": ("Saints", "#101820", "#D3BC8D"),
    "NYG": ("Giants", "#0B2265", "#A71930"),
    "NYJ": ("Jets", "#000000", "#125740"),
    "PHI": ("Eagles", "#004C54", "#A5ACAF"),
    "PIT": ("Steelers", "#101820", "#FFB612"),
    "SEA": ("Seahawks", "#002244", "#69BE28"),
    "SF": ("49ers", "#AA0000", "#B3995D"),
    "TB": ("Buccaneers", "#101820", "#D50A0A"),
    "TEN": ("Titans", "#0C2340", "#4B92DB"),
    "WSH": ("Commanders", "#5A1414", "#FFB612"),
}

# The app's own. Not a club, so it is kept out of CLUBS and offered
# separately -- "no team picked yet" is a real state, not a 33rd club.
HOUSE_COLOURS = ("Fantasy Sports Bible", "#0B1A36", "#E5B32B")

# Stored choice keys. Both are immutable storage keys (CLAUDE.md): the
# theme has always lived in ww_theme, and the club joins it in fb_team.
THEME_KEY = "ww_theme"
TEAM_KEY = "fb_team"

# What the app opens in when nothing is stored.
DEFAULT_THEME = "team"

# What an accent must clear against its own ground. Held to 3:1 -- the
# WCAG threshold for a UI element or a border, which is what an accent
# mostly *is* here. Pushing it to 4.5 turned eight clubs' second mark
# into a pastel of itself (Buffalo's red came out pink), and buttons do
# not need it: they get --color-on-accent below, chosen against the
# true accent, so the colour stays the club's and the label stays
# readable on it.
MIN_ACCENT_CONTRAST = 3.0

# The two shipped modes that are not a club.
MODES = ("team", "dark", "light")

# Themes stored before clubs existed. Neither key may be renamed, so the
# old values are translated rather than dropped -- someone who picked
# Cowboys mode in August keeps it.
LEGACY_THEMES = {"cowboys": "DAL", "titans": "TEN"}


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def luminance(value: str) -> float:
    """Relative luminance, WCAG's formula. Used to decide which of a
    club's two marks is the ground and which is the accent, and to assert
    the generated text actually contrasts with it."""
    channels = []
    for raw in _rgb(value):
        c = raw / 255
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    lo, hi = sorted((la, lb))
    return (hi + 0.05) / (lo + 0.05)


def _mix(value: str, target: tuple[int, int, int], amount: float) -> str:
    return _hex(tuple(c + (t - c) * amount for c, t in zip(_rgb(value), target, strict=True)))


def _toward_black(value: str, amount: float) -> str:
    return _mix(value, (0, 0, 0), amount)


def _toward_white(value: str, amount: float) -> str:
    return _mix(value, (255, 255, 255), amount)


def palette(dark: str, bright: str) -> dict[str, str]:
    """A full token set from a club's two marks.

    The ground is the darker mark pulled down until it is genuinely a
    page background rather than a jersey; the accent is the brighter one
    lifted until it reads on that ground. Everything between is a ramp,
    so borders, muted text and hover states all stay in the club's hue
    instead of reverting to grey.
    """
    if luminance(dark) > luminance(bright):
        dark, bright = bright, dark

    ground = _toward_black(dark, 0.55) if luminance(dark) > 0.05 else _toward_white(dark, 0.06)
    ink = _toward_white(dark, 0.93)

    # The accent has to clear the ground, and a club's second mark does
    # not always do it on its own -- Buffalo's red against Buffalo's navy
    # lands at 2.8:1, which is a button nobody can read. Lift it until it
    # does, in small steps, so a colour that already works is untouched
    # and one that does not moves the least distance that fixes it.
    accent = bright
    for _ in range(24):
        if contrast(ground, accent) >= MIN_ACCENT_CONTRAST:
            break
        accent = _toward_white(accent, 0.08)

    # What to write ON the accent. Buttons paint the accent as their
    # background, so the label needs contrast with the accent rather
    # than with the page -- and on a club whose mark is mid-toned,
    # neither the page ink nor the page ground manages it. Falling back
    # to flat black or white is not elegant; it is legible, which wins.
    on_accent = max((ink, ground, "#ffffff", "#000000"), key=lambda c: contrast(accent, c))

    return {
        "--color-bg": ground,
        "--color-text": ink,
        "--color-neutral-200": _toward_white(ground, 0.07),
        "--color-neutral-300": _toward_white(ground, 0.15),
        "--color-neutral-400": _toward_white(ground, 0.33),
        "--color-neutral-600": _toward_white(ground, 0.58),
        "--color-neutral-700": _toward_white(ground, 0.70),
        "--color-neutral-800": _toward_white(ground, 0.84),
        "--color-accent": accent,
        "--color-on-accent": on_accent,
        "--color-accent-100": _toward_black(accent, 0.72),
        "--color-accent-200": _toward_black(accent, 0.58),
        "--color-accent-400": _toward_black(accent, 0.22),
        "--color-accent-700": _toward_white(accent, 0.22),
        "--color-accent-800": _toward_white(accent, 0.46),
    }


def name(code: str) -> str:
    if code == HOUSE:
        return HOUSE_COLOURS[0]
    entry = CLUBS.get(code)
    return entry[0] if entry else code


def all_codes() -> list[str]:
    """The house theme first, then the clubs alphabetically by name."""
    return [HOUSE, *sorted(CLUBS, key=lambda c: CLUBS[c][0])]


def colours(code: str) -> tuple[str, str]:
    if code == HOUSE:
        return HOUSE_COLOURS[1], HOUSE_COLOURS[2]
    entry = CLUBS.get(code)
    return (entry[1], entry[2]) if entry else (HOUSE_COLOURS[1], HOUSE_COLOURS[2])


def stylesheet() -> str:
    """Every club's tokens, as one cacheable stylesheet.

    Selected by `[data-theme="team"][data-team="DET"]`, so choosing a club
    and choosing a mode stay independent: switching to Dark and back
    returns to the club the user picked rather than forgetting it.
    """
    blocks = []
    for code in all_codes():
        dark, bright = colours(code)
        tokens = " ".join(f"{k}: {v};" for k, v in palette(dark, bright).items())
        blocks.append(f':root[data-theme="team"][data-team="{code}"] {{ {tokens} }}')
    # No club chosen yet: the house navy, which is also what the app
    # opens in before anyone picks (owner, Aug 21).
    dark, bright = HOUSE_COLOURS[1], HOUSE_COLOURS[2]
    tokens = " ".join(f"{k}: {v};" for k, v in palette(dark, bright).items())
    blocks.append(f':root[data-theme="team"]:not([data-team]) {{ {tokens} }}')
    return "\n".join(blocks) + "\n"
