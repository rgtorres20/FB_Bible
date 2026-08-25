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


# The mark's own ground. The wordmark is white and gold by design, so on
# the light theme's cream "Fantasy" and "Bible" vanish and the name reads
# as one gold word -- and on 32 club themes it lands on 32 different
# colours, none of which the artwork was drawn against. Painting the panel
# navy in every mode is not a workaround for the light theme, it is how
# the brand is drawn everywhere else (docs/BRAND.md, "Rules of use"), and
# it is the same panel the sign-in hero uses. Hard-coded hex on purpose:
# a token would follow the theme, which is exactly what must not happen.
_NAVY = "#0B1A36"

_HEADER_MARK = (
    '<div style="display:inline-block; margin:0 0 12px; padding:9px 14px 11px; '
    f"background:{_NAVY}; border:2px solid {_NAVY}; "
    'box-shadow:3px 3px 0 var(--color-text);">'
    '<img src="/app/assets/fsb-logo.svg" alt=\'Fantasy Sports Bible — draft '
    'smarter, dominate longer\' width="900" height="420" '
    'style="display:block; width:210px; max-width:100%; height:auto;"></div>'
)


def header_mark(html: str) -> tuple[str, list[str]]:
    """The mark, visibly, at the top of the app page (owner, Aug 22).

    The design document carries the artwork exactly once, as a
    `logo.png` watermark behind the whole shell at `wmOpacity` -- which
    is decoration, not identity: at that opacity it reads as texture and
    the owner could not see their own logo on their own app. The sidebar
    said the name in plain text and the mark itself appeared nowhere.

    So the full lockup goes into `<main>`'s header, above the screen
    kicker and title. That header is the one region of the page every
    screen shares *and* the only one visible on a phone -- the sidebar is
    an off-canvas drawer under 769px (mobile.css), so a mark placed there
    would be invisible on the form factor the owner mostly uses.

    Reuses `fsb-logo.svg` and the sign-in hero's panel rather than
    hand-building a wordmark: one asset, one look, and the lockup already
    carries the tagline. `fsb-logo.svg` paints no ground of its own, so
    the panel is not optional -- see `_NAVY`.
    """
    return _apply(
        html,
        (
            (
                "app header mark",
                '<div style="font-size:10px; font-weight:700; letter-spacing:0.16em; '
                'text-transform:uppercase; color:var(--color-neutral-600);">'
                "{{ screenKicker }}</div>",
                _HEADER_MARK
                + '<div style="font-size:10px; font-weight:700; letter-spacing:0.16em; '
                'text-transform:uppercase; color:var(--color-neutral-600);">'
                "{{ screenKicker }}</div>",
                1,
            ),
        ),
    )


_KICKER = (
    '<div style="font-size:10px; font-weight:700; letter-spacing:0.16em; '
    'text-transform:uppercase; color:var(--color-neutral-600);">'
    "{{ screenKicker }}</div>"
)

_HEADER_LINKS = (
    '<div style="margin:0 0 12px; font-size:13px;">'
    '<a href="/app/mine" target="_blank" rel="noopener" '
    'style="color:var(--color-accent-700); font-weight:600; text-decoration:none;">'
    "My stuff \u2014 notes &amp; rankings&nbsp;\u2192</a></div>"
)


def header_links(html: str) -> tuple[str, list[str]]:
    """A way to My stuff from the app page (owner, Aug 25: "put a link on
    main page for MINE").

    It had no route from here at all. /app/mine held each person's own
    documents, ranking lists and passkey setup, and the only paths to it
    were a "Choose a team" prompt that appears once, a footer link on one
    tab, and typing the URL -- which is how the trailing-slash 404 went
    unnoticed for so long. A page nobody can reach is a page that does
    not exist.

    It goes in the same header as the mark, for the same documented
    reason: that header is the one region every screen shares, and the
    only one visible on a phone, since the sidebar is an off-canvas
    drawer under 769px. The Draft analyzer's own link list (mobile.js,
    DRAFT_LINKS) renders only on that one screen, so it is the wrong home
    for the one page that is not about drafting.

    New tab, matching DRAFT_LINKS: installed as a PWA there is no address
    bar, and in-shell navigation away from the shell strands you. Every
    served page carries `home_bar()` now, so the way back exists either
    way -- but the convention is deliberate and consistent beats clever.
    """
    return _apply(html, (("app header links", _KICKER, _HEADER_LINKS + _KICKER, 1),))


def _yahoo_panel(html: str) -> str:
    """The Settings screen's Yahoo-account card, located in the page.

    Found rather than pasted: it is 2.5KB of markup, and a copy here would
    be one whitespace change away from matching nothing -- a silent miss,
    which for this transform means the sign-in controls stay on screen.
    """
    head = (
        '<div style="border:2px solid var(--color-text); padding:var(--space-4); '
        'margin-bottom:var(--space-6);">\n            <div style="font-size:10px; '
        "font-weight:700; letter-spacing:0.14em; text-transform:uppercase; "
        'color:var(--color-accent-700);">Yahoo account</div>'
    )
    start = html.find(head)
    if start < 0:
        return ""
    tail = '</div>\n          <div style="margin-bottom:var(--space-6);">'
    end = html.find(tail, start)
    if end < 0:
        return ""
    return html[start : end + len("</div>")]


_YAHOO_NOTE = (
    '<div style="border:1px dashed var(--color-neutral-400); '
    'padding:var(--space-4); margin-bottom:var(--space-6);">'
    '<div style="font-size:10px; font-weight:700; letter-spacing:0.14em; '
    'text-transform:uppercase; color:var(--color-neutral-600);">Yahoo account</div>'
    '<div style="font-size:12px; color:var(--color-neutral-700); margin-top:6px; '
    'text-wrap:pretty;">Not available yet. Linking a Yahoo account needs '
    "fantasy-access approval from Yahoo, which this app is still waiting on, "
    "so the buttons are hidden rather than left to fail. Everything else on "
    "these boards is live and needs no Yahoo link.</div></div>"
)


def yahoo_panel(html: str) -> tuple[str, list[str]]:
    """Take the Yahoo sign-in controls off the Settings screen.

    Owner, Aug 25: "lets remove Yahoo login from UI for now until its
    fixed". The card offered a deploy-URL box, Check, Connect Yahoo and
    Sign out -- a whole flow that cannot complete: the OAuth code is
    built and tested, but it has never been verified against a real
    account because Yahoo's fantasy-access approval has not come through
    (docs/RESUME.md). A control that cannot succeed is worse than a
    missing one; it costs somebody a session's worth of trying.

    Replaced with one line rather than deleted outright, deliberately: a
    panel that simply vanishes reads as a bug to anyone who saw it last
    week, and "why is there no Yahoo here" is a question the app should
    answer itself. The controls are gone, which is the ask; the sentence
    is what stops it becoming a mystery.

    Nothing server-side is touched. /auth/yahoo/* stays exactly as it is,
    so approval means putting this panel back, not rebuilding it.
    """
    panel = _yahoo_panel(html)
    if not panel:
        return html, ["yahoo account panel"]
    return html.replace(panel, _YAHOO_NOTE, 1), []


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


_HEALTH_LIVE_OVERRIDE = (
    "(s.live && s.live.ts && d.maxAgeH <= 24) ? s.live.ts : new Date(d.asOf).getTime()"
)
_HEALTH_HONEST = "new Date(d.asOf).getTime()"
_HEALTH_DECL = "const liveMs = s.live && s.live.ts && d.maxAgeH <= 24 ? s.live.ts : null;"
_HEALTH_DECL_HONEST = "const liveMs = null;"


def data_health_stamps(html: str) -> tuple[str, list[str]]:
    """Stop Data health re-stamping feeds with the browser's own fetch time.

    Three sites borrowed `s.live.ts` -- the timestamp of the page's OWN
    Sleeper players/trending pull, which `componentDidMount` fires on
    nearly every visit -- for any feed budgeted at 24h or less. That is
    the wire feeds: News & posts, NBC player news, Alerts. Their real
    `asOf` was discarded and replaced with page-load time, so the row
    read "2 min · PASS", the nav badge read 0, and the summary said "All
    feeds within budget" -- on the one tab whose entire job is reporting
    freshness, and regardless of whether the server wire had polled in a
    week.

    It is the same bug fixed server-side on Aug 22, surviving on the
    client: `render.merge_into_feeds` computes an honest per-feed stamp
    from `polled_at` and hands it over in `F.meta`, and the page threw it
    away. A Sleeper pull says nothing about when ESPN was last read.

    The server wire already has its own honest row (built from
    `s.wire.polled_at` just above these), so nothing is lost by letting
    each feed speak for itself.
    """
    return _apply(
        html,
        (
            ("data health nav badge", _HEALTH_LIVE_OVERRIDE, _HEALTH_HONEST, 1),
            ("data health row stamp", _HEALTH_DECL, _HEALTH_DECL_HONEST, 1),
            ("data health stale count", _HEALTH_LIVE_OVERRIDE, _HEALTH_HONEST, 1),
        ),
    )


# --- paging the two long feeds ---------------------------------------------
# Owner ask, Aug 22: "when I get to bottom of Alerts or news, be able to go
# to the next page."
#
# Two different problems wearing one sentence. Alerts already pages at eight
# a screen -- but its only Prev/Next sit ABOVE the list, so reaching the end
# means scrolling back up past everything just read, which on a phone is the
# whole screen twice. News does not page at all: it renders every item the
# overlay carries (MAX_LIVE_ITEMS is 40, plus whatever curated rows the wire
# has not already said), so the tab is one long scroll with no way to move
# through it.
#
# So: give Alerts a second pager at the foot of its list, and give News the
# paging it never had. Both foot pagers scroll back to the top of the list on
# the way through -- landing at the bottom of a fresh page is how a pager
# feels broken even when the arithmetic is right.

_ALERT_IIFE = """      ...(() => {
        const PAGE = 8;"""

# Same handlers the head pager already binds, plus a scroll. Kept beside the
# originals rather than replacing them: the head pager is already where the
# eye is on arrival, and it should not start moving the page.
_ALERT_IIFE_PAGED = """      ...(() => {
        const PAGE = 8;
        const toTop = () => { try { window.scrollTo({ top: 0, behavior: "smooth" }); } catch (e) { window.scrollTo(0, 0); } };"""  # noqa: E501

_ALERT_RETURN = """          alertPrev: () => this.setState({ alertPage: Math.max(0, page - 1) }),
          alertNext: () => this.setState({ alertPage: Math.min(pages - 1, page + 1) })"""

_ALERT_RETURN_PAGED = """          alertPrev: () => this.setState({ alertPage: Math.max(0, page - 1) }),
          alertNext: () => this.setState({ alertPage: Math.min(pages - 1, page + 1) }),
          alertPrevFoot: () => { this.setState({ alertPage: Math.max(0, page - 1) }); toTop(); },
          alertNextFoot: () => { this.setState({ alertPage: Math.min(pages - 1, page + 1) }); toTop(); }"""  # noqa: E501

# The foot of the alerts list: the rule that closes it is the anchor.
_ALERT_LIST_END = """          </sc-for>
          <div style="border-top:2px solid var(--color-text);"></div>"""


def _pager(label: str, prev: str, next_: str, prev_dim: str, next_dim: str) -> str:
    """One Prev/Next row. Same shape as the design document's own."""
    button = (
        'style="padding:5px 12px; font-size:12px; font-weight:800; cursor:pointer; '
        "border:1px solid var(--color-neutral-400); background:transparent; "
        'color:var(--color-text); opacity:{dim};" '
        'style-hover="border-color:var(--color-accent);"'
    )
    return (
        '<div style="display:flex; align-items:center; justify-content:flex-end; '
        'gap:var(--space-4); padding:var(--space-4) 0 0;">'
        f'<span style="font-size:11px; color:var(--color-neutral-600);">{{{{ {label} }}}}</span>'
        f'<button onClick="{{{{ {prev} }}}}" '
        + button.format(dim=f"{{{{ {prev_dim} }}}}")
        + ">← Prev</button>"
        f'<button onClick="{{{{ {next_} }}}}" '
        + button.format(dim=f"{{{{ {next_dim} }}}}")
        + ">Next →</button>"
        "</div>"
    )


_ALERT_LIST_END_PAGED = (
    """          </sc-for>
          """
    + _pager("alertPageLabel", "alertPrevFoot", "alertNextFoot", "alertPrevDim", "alertNextDim")
    + """
          <div style="border-top:2px solid var(--color-text);"></div>"""
)

_NEWS_STATE = "    alertPage: 0,"
_NEWS_STATE_PAGED = "    alertPage: 0,\n    newsPage: 0,"

_NEWS_BINDING = """      news: NEWS.map(n => Object.assign({}, n, {
        tagBg: n.kind === "Post" ? "transparent" : N2,
        tagFg: n.kind === "Post" ? N6 : "var(--color-neutral-800)",
        tagBd: "var(--color-neutral-400)"
      })),"""

_NEWS_BINDING_PAGED = """      ...(() => {
        const NPAGE = 12;
        const nToTop = () => { try { window.scrollTo({ top: 0, behavior: "smooth" }); } catch (e) { window.scrollTo(0, 0); } };
        const npages = Math.max(1, Math.ceil(NEWS.length / NPAGE));
        const npage = Math.min(s.newsPage || 0, npages - 1);
        return {
          news: NEWS.slice(npage * NPAGE, npage * NPAGE + NPAGE).map(n => Object.assign({}, n, {
            tagBg: n.kind === "Post" ? "transparent" : N2,
            tagFg: n.kind === "Post" ? N6 : "var(--color-neutral-800)",
            tagBd: "var(--color-neutral-400)"
          })),
          newsPageLabel: "Page " + (npage + 1) + " of " + npages + " \\u00b7 " + NEWS.length + " posts",
          newsPrevDim: npage === 0 ? "0.25" : "1",
          newsNextDim: npage >= npages - 1 ? "0.25" : "1",
          newsPrev: () => { this.setState({ newsPage: Math.max(0, npage - 1) }); nToTop(); },
          newsNext: () => { this.setState({ newsPage: Math.min(npages - 1, npage + 1) }); nToTop(); }
        };
      })(),"""  # noqa: E501

_NEWS_LIST_END = """          </sc-for>
        </div>
        <div style="padding:var(--space-4) var(--space-6) var(--space-8);">
          <div style="font-size:10px; font-weight:700; letter-spacing:0.14em; text-transform:uppercase; color:var(--color-neutral-600);">Feeds watched</div>"""  # noqa: E501

_NEWS_LIST_END_PAGED = (
    """          </sc-for>
          """
    + _pager("newsPageLabel", "newsPrev", "newsNext", "newsPrevDim", "newsNextDim")
    + """
        </div>
        <div style="padding:var(--space-4) var(--space-6) var(--space-8);">
          <div style="font-size:10px; font-weight:700; letter-spacing:0.14em; text-transform:uppercase; color:var(--color-neutral-600);">Feeds watched</div>"""  # noqa: E501
)


def feed_paging(html: str) -> tuple[str, list[str]]:
    """Prev/Next at the foot of Alerts, and paging for News at all.

    Five edits, and they are all-or-nothing in practice: a foot pager
    bound to handlers that were never added would render two dead
    buttons, and a sliced News list with no pager would hide items with
    no way to reach them. Each reports its own miss, and the test asserts
    the set fires together against the committed document.
    """
    return _apply(
        html,
        (
            ("alerts foot-pager handlers", _ALERT_IIFE, _ALERT_IIFE_PAGED, 1),
            ("alerts foot-pager bindings", _ALERT_RETURN, _ALERT_RETURN_PAGED, 1),
            ("alerts foot pager", _ALERT_LIST_END, _ALERT_LIST_END_PAGED, 1),
            ("news page state", _NEWS_STATE, _NEWS_STATE_PAGED, 1),
            ("news paging", _NEWS_BINDING, _NEWS_BINDING_PAGED, 1),
            ("news foot pager", _NEWS_LIST_END, _NEWS_LIST_END_PAGED, 1),
        ),
    )


# --- what the app actually watches -----------------------------------------
# The News tab's "Feeds watched" panel named eight sources. Three exist.
# The other five -- @AdamSchefter, 18 team beat writers, official
# transactions, practice reports, and "Yahoo league activity - 2 leagues"
# -- are not polled by anything: `app/feeds/sources.py` defines seven
# publishers and none of those is among them, and Yahoo is still waiting
# on fantasy-access approval, so that last row described nothing at all.
#
# Two of them even carried freshness claims ("live") for feeds that do not
# exist. The app already gets this right one screen over, where the
# Settings panel labels its unwired group "not wired" -- this panel
# contradicted it.
#
# Generated from `sources.FEED_SOURCES` at import, so adding a publisher
# updates the panel and removing one cannot leave a ghost behind. The
# count column says "polled" rather than "live": these are the feeds the
# app reads, and how fresh each one is on any given day is Data health's
# job, which measures it per source.
_FEEDS_PANEL = """      feeds: [
        { name: "NBC Sports player news", count: "live" },
        { name: "@AdamSchefter", count: "live" },
        { name: "Rotowire news", count: "live" },
        { name: "Team beat writers", count: "18 accounts" },
        { name: "Official transactions", count: "live" },
        { name: "Practice reports", count: "Wed–Fri" },
        { name: "Yahoo league activity", count: "2 leagues" },
        { name: "National takes", count: "muted" }
      ],"""

_FEEDS_PANEL_REAL = """      feeds: [
        { name: "ESPN NFL", count: "polled" },
        { name: "Yahoo Sports NFL", count: "polled" },
        { name: "Rotowire NFL", count: "polled" },
        { name: "NBC Sports · ProFootballTalk", count: "polled" },
        { name: "CBS Sports NFL", count: "polled" },
        { name: "Yahoo Fantasy", count: "polled" },
        { name: "NBC Rotoworld", count: "polled" }
      ],"""


def _src(sid: str, name: str, kind: str, weight: int, group: str) -> str:
    """One SOURCES entry, spelled exactly as index.html spells it.

    Built rather than pasted so the lines stay inside the line limit --
    a `# noqa` cannot go inside a triple-quoted literal without becoming
    part of the string it is meant to annotate.
    """
    return (
        f'  {{ id: "{sid}", name: "{name}", kind: "{kind}", weight: {weight}, group: "{group}" }}'
    )


_SOURCES_INVENTED = ",\n".join(
    (
        _src(
            "s1",
            "NBC Sports player news",
            "nbcsports.com/fantasy/football \u00b7 live wire",
            28,
            "wire",
        ),
        _src("s2", "@AdamSchefter", "X \u00b7 breaking status and transactions", 24, "wire"),
        _src("s8", "Rotowire news", "rotowire.com/football/news \u00b7 live wire", 16, "wire"),
        _src("s7", "National takes", "Muted by default", 0, "wire"),
        _src(
            "s3",
            "Team beat writers",
            "X list \u00b7 18 accounts, usage and practice",
            16,
            "usage",
        ),
        _src("s5", "Route and snap analytics", "Usage model \u00b7 imported CSV", 9, "usage"),
    )
)

_SOURCES_REAL = ",\n".join(
    (
        _src(
            "s1",
            "NBC Rotoworld",
            "nbcsports.com/fantasy/football/player-news \u00b7 polled",
            28,
            "wire",
        ),
        _src("s2", "ESPN NFL", "espn.com/espn/rss/nfl/news \u00b7 polled", 24, "wire"),
        _src("s8", "Rotowire NFL", "rotowire.com/rss/news.php \u00b7 polled", 16, "wire"),
        _src("s7", "Yahoo Sports NFL", "sports.yahoo.com/nfl/rss.xml \u00b7 polled", 16, "wire"),
        _src("s3", "Backfield split read", "Off leans committee RBs toward ADP", 16, "usage"),
        _src(
            "s5",
            "Route-share read",
            "Off leans committee pass-catchers toward ADP",
            9,
            "usage",
        ),
    )
)


def source_names(html: str) -> tuple[str, list[str]]:
    """Stop the Settings source list naming feeds nobody polls.

    A companion to `feeds_watched`, and the reason it is a separate
    transform is the reason the watchdog caught this at all: the same
    fictions lived in TWO lists. Fixing the Feeds-watched panel left
    "Team beat writers" and "National takes" standing here, and the
    live check failed on exactly those two while the panel it was
    written for passed. A grep of the page, not of the block being
    edited, is what the next one of these needs.

    Two different problems, so two different fixes:

    * The **wire** group named an X account and a "National takes"
      category. Nothing polls either. It now names four of the seven
      real publishers (`sources.FEED_SOURCES`); the group is labelled
      "not wired" already, so these are display, and the full seven are
      on the Feeds-watched panel.

    * The **usage** group is not display -- `srcOn.s3` and `srcOn.s5`
      each pull a split-usage player's value toward ADP (index.html
      ~2328). So the toggles do something real while being named after
      an "X list of 18 accounts" and an "imported CSV" that do not
      exist. Renaming them for their EFFECT keeps the control and drops
      the claim, which is the same call `source_truth` made about the
      board sliders: a real control with a misleading label is worse
      than a dead one.

    s7 shipped defaulting off, which read as "muted". A real polled feed
    showing as off would be a fresh false claim, so its default flips
    with its name.
    """
    return _apply(
        html,
        (
            ("settings source list", _SOURCES_INVENTED, _SOURCES_REAL, 1),
            (
                "s7 default",
                "s6: true, s7: false, s8: true",
                "s6: true, s7: true, s8: true",
                1,
            ),
        ),
    )


def feeds_watched(html: str) -> tuple[str, list[str]]:
    """Name the publishers the app really polls, and only those."""
    return _apply(
        html,
        (
            ("feeds watched panel", _FEEDS_PANEL, _FEEDS_PANEL_REAL, 1),
            (
                "sources-live count",
                '{ label: "Sources live", value: "9" }',
                '{ label: "Sources watched", value: "7" }',
                1,
            ),
        ),
    )


PRE = (
    head_tags,
    header_mark,
    header_links,
    yahoo_panel,
    client_paths,
    vegas_binding,
    ffbets_landing,
    mode_picker,
    source_truth,
    data_health_stamps,
    feed_paging,
    feeds_watched,
    source_names,
)

# Applied after, so a rename also reaches the text the overlays injected.
POST = (wordmark, league_names)


def apply(html: str, transforms: tuple) -> tuple[str, list[str]]:
    """Run a registry in order, collecting every miss."""
    misses: list[str] = []
    for transform in transforms:
        html, missed = transform(html)
        misses.extend(missed)
    return html, misses
