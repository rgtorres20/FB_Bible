"""Named, owned transforms of the served page.

`frontend/index.html` is a generated design document that stays
byte-identical on disk (docs/MIGRATION.md), so everything the app adds to
it is a serve-time edit. Those edits used to be fifteen inline
`html.replace()` calls in `main.py`, belonging to nobody, testable only
through the whole page.

Two problems that caused, both of which this module exists to fix:

1. **Nobody owned them.** Two people editing the served page edited the
   same function. Splitting the work across agents was impossible.
2. **A miss was silent.** `html.replace()` on an anchor the design
   document no longer contains returns the html unchanged and reports
   nothing. The page still serves, missing a feature, and looks fine.
   That is the same failure as a slider wired to nothing: you cannot tell
   "working" from "not running at all".

So every transform here reports which of its anchors it did *not* find.
`apply()` collects the misses and the caller logs them. A design resync
that renames a literal now says so instead of quietly dropping a feature.

Adding a transform: write the function, add it to `PRE` or `POST`, and
add a case to `tests/test_page.py` asserting it fires on the real page
and reports a miss when its anchor is absent.
"""

from __future__ import annotations

from . import skin

# One edit: a label for the miss report, the anchor to find, its
# replacement, how many occurrences to replace (0 = all of them), and
# whether finding nothing is acceptable.
#
# `optional` exists for cleanup passes -- an edit whose job is "make sure
# none of this survives". Finding nothing to clean is success, not a
# missing feature, so reporting it as a miss would train us to ignore
# the miss report. Everything else defaults to required.
Edit = tuple[str, str, str, int] | tuple[str, str, str, int, bool]


def _apply(html: str, edits: tuple[Edit, ...]) -> tuple[str, list[str]]:
    """Apply edits in order; return the html and the labels that missed.

    A miss is not an error here -- the caller decides. It is information,
    and the whole point of this module is that it stops being invisible.
    """
    misses: list[str] = []
    for edit in edits:
        label, old, new, count = edit[:4]
        optional = edit[4] if len(edit) > 4 else False
        if old not in html:
            if not optional:
                misses.append(label)
            continue
        html = html.replace(old, new, count) if count else html.replace(old, new)
    return html, misses


def head_tags(html: str) -> tuple[str, list[str]]:
    """The mobile stylesheet, the menu script, the mark and the theme boot.

    The favicon and boot are injected rather than committed into the
    design document so a resync from the design project cannot silently
    drop the brand or leave the page on the wrong club (docs/BRAND.md).
    The club palette applies to <html> before first paint; the page's own
    token blocks are [data-skin][data-theme] pairs on its runtime's
    element, so "team" matches none of them and these :root values
    inherit through instead of fighting it.
    """
    return _apply(
        html,
        (
            (
                "head tags",
                "</head>",
                '<link rel="stylesheet" href="mobile.css">'
                '<script src="mobile.js" defer></script>'
                f"{skin.FAVICON}{skin.THEME_BOOT}</head>",
                1,
            ),
        ),
    )


def client_paths(html: str) -> tuple[str, list[str]]:
    """The dynamic imports carry the design project's layout.

    In that project the API client lives at "./frontend/lib/..."; served
    from /app/ it lives at ./lib/. Without this both the Yahoo link check
    and the 24h yahoo-cache purge fail with "API client failed to load".
    Same class of fix sw.js already carries for its precache list.
    """
    return _apply(
        html,
        (
            (
                "fbApi import path",
                'import("./frontend/lib/fbApi.js")',
                'import("./lib/fbApi.js")',
                0,
            ),
        ),
    )


def vegas_binding(html: str) -> tuple[str, list[str]]:
    """Rebind the committed VEGAS table to the fetched data file.

    F is the parsed feeds.json in the page's scope; the `||` keeps the
    committed table as the fallback when the overlay has no lines.
    """
    return _apply(
        html,
        (("vegas table binding", "vegas: VEGAS,", "vegas: (F.vegas || VEGAS),", 1),),
    )


def ffbets_landing(html: str) -> tuple[str, list[str]]:
    """FFBets opens on Predictions; Build-a-team is shelved (owner, Aug 15).

    Serve-time only -- the builder's code stays intact on disk and in
    git, just unreferenced in the served copy, so restoring it is
    deleting these two edits.
    """
    return _apply(
        html,
        (
            ("FFBets landing mode", 'gdMode: "build",', 'gdMode: "predict",', 1),
            (
                "Build-a-team tab",
                '[{ id: "build", label: "Build a team" }, { id: "predict", label: "Predictions" }]',
                '[{ id: "predict", label: "Predictions" }]',
                1,
            ),
        ),
    )


def mode_picker(html: str) -> tuple[str, list[str]]:
    """My team / Dark / Light (owner, Aug 21).

    The club is whichever of the 32 the user chose, and the house navy
    until they choose one. Cowboys and Titans modes were the first two of
    those 32; they stopped being special, so the hand-written pair comes
    out and `data-team` decides. The retired values stay accepted in the
    restore guard so a browser still holding one is *translated* rather
    than reset -- skin.THEME_BOOT does the translating.
    """
    return _apply(
        html,
        (
            (
                "mode picker option",
                '<option value="cowboys">★ Cowboys mode</option>',
                '<option value="team">★ My team</option>',
                1,
            ),
            (
                "mode picker label",
                'themeLabel: s.theme === "cowboys" ? "★ Cowboys mode"',
                'themeLabel: s.theme === "team" ? "★ My team"',
                1,
            ),
            (
                "stored-theme restore guard",
                'if (th === "dark" || th === "light" || th === "cowboys")',
                'if (th === "dark" || th === "light" || th === "team" ||'
                ' th === "cowboys" || th === "titans")',
                1,
            ),
            # The page's own default state was light. Owner, Aug 21:
            # "home page should be the dark blue not light mode" -- it
            # opens on the club theme, the house navy until a club is picked.
            ("default theme", 'theme: "light"', 'theme: "team"', 1),
            # The page's skin hook only ever knew "cowboys". The club
            # palettes come from /app/teams.css via data-team instead, so
            # this stops the page forcing a Dallas skin on everyone.
            (
                "skin hook",
                'skin: "cowboys",',
                'skin: s.theme === "team" ? "team" : "none",',
                1,
            ),
        ),
    )


def wordmark(html: str) -> tuple[str, list[str]]:
    """The app's name in the sidebar, so a resync cannot revert it."""
    return _apply(
        html,
        ((">FANTASY BIBLE<", ">FANTASY BIBLE<", ">FANTASY SPORTS BIBLE<", 1),),
    )


def league_names(html: str) -> tuple[str, list[str]]:
    """The real league names (docs/LEAGUES.md, owner request).

    The design document still says "Sunday Gravy" / "The Trenches"
    everywhere -- picker values, curated alert rows, helper copy, and the
    board's injected ADP toggle. One late pass renames every occurrence,
    page and injected snippets alike, so the picker values and the code
    comparing against them move together. Full names first, then the bare
    shorthands the curated copy uses.
    """
    return _apply(
        html,
        (
            ("league name Sunday Gravy", "Sunday Gravy", "NDDPL", 0),
            ("league name The Trenches", "The Trenches", "RED_EYE", 0),
            # Optional: cleanup passes for the bare shorthands the
            # curated copy used to use. The Aug 21 design resync removed
            # every bare "Gravy" -- all 22 occurrences are now inside
            # "Sunday Gravy", so this finds nothing and that is correct.
            # The postcondition is what matters and it has its own test:
            # no design-document league name survives.
            ("league shorthand Gravy", "Gravy", "NDDPL", 0, True),
            ("league shorthand Trenches", "Trenches", "RED_EYE", 0, True),
        ),
    )


def stage_badge(html: str) -> tuple[str, list[str]]:
    """A beta deploy announces itself (styles in mobile.css).

    Only called for the preview stage; prod and local serve no badge.
    """
    return _apply(
        html,
        (("beta badge", "</body>", '<div id="fb-stage-badge">BETA</div></body>', 1),),
    )


# Applied before the live overlays, which need the page's own tables
# present to rebind them.
# The analyzer's small-caps label markup, shared by the anchor and its
# replacement so the two cannot drift apart.
_LABEL = (
    '<span style="font-size:10px; font-weight:700; letter-spacing:0.14em; '
    'text-transform:uppercase; color:var(--color-neutral-600);">'
)


def source_truth(html: str) -> tuple[str, list[str]]:
    """Stop the Settings panel claiming to blend lists it does not have.

    Two different things called "sources" ended up side by side, and the
    panel described the wrong one.

    The four board entries -- "Aggregate ADP", "ESPN draft kit", "Yahoo
    consensus top-300", "My own tiers" -- are hand-written names with no
    data behind any of them. Their sliders are not weightless, though:
    the three "trusted" ones and the one "own" one compute a single
    ratio, `srcWeight`, which tilts the draft board between its own tier
    order and live ADP. That is a real control with a misleading label,
    which is worse than a dead one -- a dead control teaches you to stop
    touching it.

    Meanwhile the *actual* ranking lists (app/feeds/ranklists.py) blend
    with no weights at all. So the panel's note -- "Each list's share
    blends into Draft analyzer order" -- describes code that was deleted
    on Aug 21.

    The fix is naming, not deletion. The four sliders keep working
    because they do something; the group stops calling them rank lists,
    and points at where the real ones live. Same for the analyzer's own
    slider, whose caption promised "pure ESPN/Yahoo ADP blend".
    """
    return _apply(
        html,
        (
            (
                "settings board-mix title",
                '{ title: "Rank lists — draft board", tag: activeSources.length + " in blend", '
                'tagColor: "var(--color-accent-700)",',
                '{ title: "Board order mix", tag: "sets one number", '
                'tagColor: "var(--color-neutral-600)",',
                1,
            ),
            (
                "settings board-mix note",
                "note: \"The only weights that work. Each list's share blends into Draft "
                'analyzer order, alongside the rank-vs-ADP slider on the board.",',
                'note: "These four set one number between them: how far the draft board '
                "leans on live ADP versus your own tier order. They are not loaded "
                "ranking lists — those carry no weights at all, count equally when "
                "switched on, and live under Source lists in the Draft analyzer "
                '(add or remove them at /app/mine).",',
                1,
            ),
            (
                "analyzer slider label",
                _LABEL + "Source influence</span>",
                _LABEL + "Board order</span>",
                1,
            ),
            (
                "analyzer slider caption",
                "0 = your tier order · 100 = pure ESPN/Yahoo ADP blend",
                "0 = your own tier order · 100 = live ADP. Separate from the ranking "
                "lists below, which are blended equally.",
                1,
            ),
        ),
    )


PRE = (head_tags, client_paths, vegas_binding, ffbets_landing, mode_picker, source_truth)

# Applied after, so a rename also reaches the text the overlays injected.
POST = (wordmark, league_names)


def apply(html: str, transforms: tuple) -> tuple[str, list[str]]:
    """Run a registry in order, collecting every miss."""
    misses: list[str] = []
    for transform in transforms:
        html, missed = transform(html)
        misses.extend(missed)
    return html, misses
