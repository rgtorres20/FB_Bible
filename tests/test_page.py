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

from app.feeds import board, page

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


def test_data_health_stops_restamping_feeds_with_the_browsers_own_fetch(index_html):
    """Three sites borrowed `s.live.ts` — the page's OWN Sleeper pull,
    fired on nearly every visit — for any feed budgeted 24h or less. That
    is the wire feeds, and their real as-of was discarded: the row read
    "2 min · PASS", the badge read 0, and the summary said "All feeds
    within budget", on the tab whose only job is reporting freshness. The
    server already hands over an honest per-feed stamp in F.meta; the
    page threw it away."""
    out, misses = page.data_health_stamps(index_html)
    assert not misses
    assert "s.live.ts && d.maxAgeH" not in out, "no site still borrows the Sleeper pull time"
    assert out.count("new Date(d.asOf).getTime()") == 3, "all three read the feed's own stamp"
    assert "const liveMs = null;" in out


def test_the_data_health_transform_reports_a_miss_rather_than_half_applying():
    _, misses = page.data_health_stamps("<html>nothing to patch</html>")
    assert len(misses) == 3


# The Aug 24 miss, kept as a test. `feeds_watched` removed five invented
# publishers from the Feeds-watched panel and every unit test passed --
# but two of them, "Team beat writers" and "National takes", also lived in
# the Settings SOURCES list, and the live watchdog failed on exactly those
# while the panel check beside it passed. A transform's own anchor test
# proves it fired; it cannot prove the claim is gone from the PAGE. So
# this asserts against the whole served output, which is the only thing a
# reader actually sees.
INVENTED_PUBLISHERS = (
    "Team beat writers",
    "Practice reports",
    "National takes",
    "Official transactions",
    "Yahoo league activity",
    "Route and snap analytics",
)


def test_no_invented_publisher_survives_anywhere_on_the_page(index_html):
    served, misses = page.apply(index_html, page.PRE)

    assert misses == []
    still = [n for n in INVENTED_PUBLISHERS if n in served]
    assert not still, f"invented sources still on the page: {still}"


def test_the_usage_toggles_keep_the_ids_their_behaviour_hangs_off(index_html):
    """s3 and s5 are not decoration -- each pulls a split-usage player's
    value toward ADP. Renaming them for their effect is the fix; renaming
    the IDs would silently unwire two real controls."""
    served, _ = page.apply(index_html, page.PRE)

    assert 'id: "s3"' in served and 'id: "s5"' in served
    assert "srcOn.s3" in served and "srcOn.s5" in served


def test_a_polled_feed_is_not_shown_switched_off(index_html):
    """s7 shipped defaulting off and reading "Muted by default". It now
    names a feed the app really polls, so leaving it off would trade one
    false claim for another."""
    served, _ = page.apply(index_html, page.PRE)

    assert "s7: true" in served


# --- the draft analyzer's league picker (owner, Aug 25) ----------------------
# Two reports, one cause: "I don't see any updates when it comes to adding
# leagues in draft analyzer" and "I don't see my 3rd league either". The page
# hardcoded the design document's two, so BALLAPALOSA -- verified, scored, and
# already on /app/scoring, /app/idp and the mock room -- was invisible here,
# and a league defined at /app/leagues never appeared at all.


def test_every_league_reaches_the_analyzer(index_html):
    from app import leagues as leagues_mod

    served, n = board.inject_leagues(index_html, leagues_mod.defaults())

    assert n == len(leagues_mod.defaults()) == 3
    for lg in leagues_mod.defaults():
        assert f'id: "{lg.name}"' in served, lg.name
    assert 'meta: "3 connected"' in served


def test_a_league_the_user_defined_reaches_it_too(index_html):
    """The picker is built from the caller's list, not from the defaults,
    which is what makes /app/leagues actually show up here."""
    from app import leagues as leagues_mod

    mine = leagues_mod.defaults()[:1]
    served, n = board.inject_leagues(index_html, mine)

    assert n == 1
    assert 'meta: "1 connected"' in served
    assert 'id: "RED_EYE"' not in served


def test_the_per_league_state_moves_with_the_picker(index_html):
    """A picker offering a league whose state map has no slot for it
    renders a league that silently drops every pick made in it. So the
    maps, their defaults and the queue badge all move together."""
    from app import leagues as leagues_mod

    served, _ = board.inject_leagues(index_html, leagues_mod.defaults())

    for key in ("myTeams", "taken", "queue", "draftSlot"):
        line = next(ln for ln in served.splitlines() if ln.strip().startswith(f"{key}:"))
        for lg in leagues_mod.defaults():
            assert f'"{lg.name}"' in line, f"{lg.name} missing from {key}"
    assert 'draftLeague: "NDDPL"' in served
    assert 'queueLeague: "NDDPL"' in served


def test_saved_teams_survive_the_rename(index_html):
    """The subtle one. The guards read

        if (teams && teams["Sunday Gravy"] && teams["The Trenches"])

    so stored data had to carry BOTH design names or it was thrown away
    whole -- which, once the keys are real league names, discards every
    saved team on load. A shape check, then a merge onto the defaults, so
    a league missing from storage keeps its empty slot instead of
    vanishing from state."""
    from app import leagues as leagues_mod

    served, _ = board.inject_leagues(index_html, leagues_mod.defaults())

    # Scoped to the guards. The curated alert rows still say "Sunday
    # Gravy" at this point -- page.league_names renames those later, in
    # POST -- so asserting the string is gone from the whole page would be
    # testing the wrong layer and would fail for the right reason.
    assert 'teams["Sunday Gravy"]' not in served
    assert 'qq["Sunday Gravy"]' not in served
    assert 'taken["Sunday Gravy"]' not in served
    assert served.count("Object.assign({}, this.state.myTeams, teams)") == 1
    assert served.count("Object.assign({}, this.state.queue, qq)") == 1
    assert served.count("Object.assign({}, this.state.taken, taken)") == 1


def test_a_missing_anchor_changes_nothing(index_html):
    """All-or-nothing, same rule as inject_league_points: a picker updated
    beside a state map that was not would be worse than the bug."""
    from app import leagues as leagues_mod

    broken = index_html.replace('draftLeague: "Sunday Gravy",', "draftLeague: 0,", 1)
    served, n = board.inject_leagues(broken, leagues_mod.defaults())

    assert n == 0
    assert served == broken


def test_the_blurb_is_derived_not_typed(index_html):
    """The two strings on the page were hand-typed -- a second home for a
    league's facts, and so a second place for them to be wrong. Every
    claim in the line now comes off the League itself."""
    from app import leagues as leagues_mod

    by_name = {lg.name: lg for lg in leagues_mod.defaults()}

    nddpl = board.league_blurb(by_name["NDDPL"])
    assert "10-team" in nddpl and "IDP" in nddpl
    assert "per completion" not in nddpl, "NDDPL has no completion bonus"

    # BALLAPALOSA starts a team defence, not defenders, and does NOT halve
    # receiving yardage -- the two things separating it from the other two.
    balla = board.league_blurb(by_name["BALLAPALOSA"])
    assert "team D/ST" in balla
    assert "IDP" not in balla
    assert "rec yds/pt" not in balla


def test_the_app_page_offers_a_way_to_my_stuff(index_html):
    """Owner, Aug 25: "put a link on main page for MINE".

    /app/mine had no route from the app page at all -- the paths to it
    were a "Choose a team" prompt that shows once, a footer link on a
    single tab, and typing the URL. Which is also how the trailing-slash
    404 stayed hidden: nobody could reach it the easy way to notice.
    """
    served, misses = page.apply(index_html, page.PRE)

    assert misses == []
    assert 'href="/app/mine"' in served
    assert "My stuff" in served


def test_the_my_stuff_link_sits_in_the_header_every_screen_shares(index_html):
    """Not in DRAFT_LINKS, which renders only on the Draft analyzer. It
    goes in the same header as the mark, for the same documented reason:
    the one region every screen shares, and the only one visible on a
    phone, since the sidebar is an off-canvas drawer under 769px."""
    served, _ = page.apply(index_html, page.PRE)

    link_at = served.index('href="/app/mine"')
    mark_at = served.index("fsb-logo.svg")
    kicker_at = served.index("{{ screenKicker }}")
    assert mark_at < link_at < kicker_at, "link should sit between the mark and the kicker"


def test_the_my_stuff_link_opens_out_of_the_shell(index_html):
    """Matches DRAFT_LINKS. Installed as a PWA there is no address bar,
    and navigating the shell away from itself strands you."""
    served, _ = page.apply(index_html, page.PRE)

    tag = served[served.index('<a href="/app/mine"') : served.index('href="/app/mine"') + 220]
    assert 'target="_blank"' in tag
    assert 'rel="noopener"' in tag


def test_no_hardcoded_league_list_survives_anywhere(index_html):
    """The miss that made the first fix look done while the owner still
    could not see their third league.

    inject_leagues edited the sidebar's `leagueDefs`, passed its own
    anchor checks, and left FIVE other hardcoded pairs standing --
    including `draftLeagues`, which is the list the Draft analyzer
    actually renders. An all-or-nothing transform only guarantees the
    edits it knows about.

    So this greps the WHOLE served page, exactly like the invented-
    publishers test written the same day after the same mistake. Curated
    alert rows are excluded: those carry `league: "..."` as content and
    page.league_names renames them later, in POST.
    """
    from app import leagues as leagues_mod

    served, misses = page.apply(index_html, page.PRE)
    served, _ = board.inject_leagues(served, leagues_mod.defaults())
    served, post_misses = page.apply(served, page.POST)

    assert misses == [] and post_misses == []
    for doc_name in ("Sunday Gravy", "The Trenches"):
        assert doc_name not in served, f"{doc_name} still on the page"


def test_every_surface_naming_leagues_names_all_of_them(index_html):
    """Each list the page keeps of its leagues, by the shape that list
    takes. Named individually so a failure says WHICH one drifted rather
    than just that something did."""
    from app import leagues as leagues_mod

    served, _ = board.inject_leagues(index_html, leagues_mod.defaults())
    names = [lg.name for lg in leagues_mod.defaults()]

    for label, needle in (
        ("sidebar picker", "const leagueDefs = ["),
        ("analyzer chips", "draftLeagues: ["),
        ("queue pills", "queueLeaguePills: ["),
        ("seat counts", "const leagueTeams = {"),
        ("yahoo ids", "const QID = {"),
        ("settings cards", "leagueSettings: ["),
    ):
        at = served.index(needle)
        chunk = served[at : at + 900]
        for name in names:
            assert name in chunk, f"{name} missing from the {label}"


def test_a_league_with_no_yahoo_id_gets_no_link(index_html):
    """A league somebody defined by hand has no id, so it must get an
    empty url -- never inherit one. `blank()` builds with dataclass
    replace() off NDDPL, which silently carried the OWNER'S league id
    until it was cleared: a stranger's settings page linking to the
    owner's Yahoo league."""
    from app import leagues as leagues_mod

    mine = leagues_mod.blank("Sunday Money", 12)

    assert mine.yahoo_id == ""
    card = board.league_facts(mine)
    assert 'url: ""' in card
    assert "192426" not in card

    served, _ = board.inject_leagues(index_html, [*leagues_mod.defaults(), mine])
    qid_at = served.index("const QID = {")
    assert "Sunday Money" not in served[qid_at : qid_at + 300], "no id means no QID entry"


# --- the Blend column (owner, Aug 25) ---------------------------------------
# "i still dont see updates to adp when i move sliders". ADP is market data
# and never moves. But the column beside it is headed Blend, and it was not
# the blend: the board SORTED by blendScore (the only place srcWeight has any
# effect) and DISPLAYED b.base, which srcWeight never touches. Measured on the
# page's own rows: 0 of 204 numbers responded to the slider; now 204 of 204.


def test_the_blend_column_is_the_number_the_board_sorts_by(index_html):
    served, n = board.wire_blend_column(index_html)

    assert n == 1
    assert "const v = blendScore(b);" in served
    assert "let v = b.base;" not in served, "the displayed value was not the sorted one"


def test_the_slider_reaches_the_displayed_value(index_html):
    """srcWeight must appear in the function the column now reads."""
    served, _ = board.wire_blend_column(index_html)

    fn = served[served.index("const blendScore") : served.index("const boardOrdered")]
    assert "(1 - w) * b.rank + w * mkt" in fn, "srcWeight is not in the displayed formula"


def test_both_usage_toggles_still_do_something(index_html):
    """They moved INTO blendScore rather than being dropped. A control that
    stops working is not an improvement on one you cannot see working."""
    served, _ = board.wire_blend_column(index_html)

    fn = served[served.index("const blendScore") : served.index("const boardOrdered")]
    assert "!beatOn" in fn and "!analyticsOn" in fn


def test_it_fires_after_deepen_has_rewritten_those_lines(index_html):
    """The trap this nearly fell into. `deepen` runs first and rewrites the
    same lines to read live ADP -- parseFloat(b.adp) becomes FBAdp(b). A
    string anchor matches the committed page (which is what a test with no
    ADP data sees) and silently misses the deployed one: a green test over a
    dead control in production."""
    simulated = index_html
    for old, new in board._CONSUMERS:
        simulated = simulated.replace(old, new)
    simulated = simulated.replace(board._WEIGHT_LINE, board._HELPER, 1)
    assert "FBAdp(b)" in simulated, "the fixture no longer resembles deepen's output"

    served, n = board.wire_blend_column(simulated)

    assert n == 1
    assert "const v = blendScore(b);" in served
    # The live-ADP reader is preserved, not overwritten by the committed line.
    fn = served[served.index("const blendScore") : served.index("const boardOrdered")]
    assert "const adp = FBAdp(b);" in fn
    assert "parseFloat(b.adp)" not in fn


def test_a_missing_anchor_reports_zero_rather_than_half_wiring_it(index_html):
    broken = index_html.replace("let v = b.base;", "let v = 0;", 1)

    served, n = board.wire_blend_column(broken)

    assert n == 0


def test_the_yahoo_sign_in_controls_are_gone(index_html):
    """Owner, Aug 25: "lets remove Yahoo login from UI for now until its
    fixed". The card offered a deploy-URL box, Check, Connect Yahoo and
    Sign out -- a flow that cannot complete, because Yahoo's
    fantasy-access approval has never come through (docs/RESUME.md). A
    control that cannot succeed costs somebody a session's worth of
    trying."""
    served, misses = page.apply(index_html, page.PRE)

    assert misses == []
    for gone in ("Connect Yahoo", "Link a Yahoo account", "{{ yahooConnect }}"):
        assert gone not in served, gone


def test_no_orphaned_yahoo_binding_is_left_behind(index_html):
    """Every handler the removed card bound. A binding with no panel is a
    template referencing a callback nothing renders."""
    served, _ = page.apply(index_html, page.PRE)

    for binding in (
        "{{ yahooCheck }}",
        "{{ yahooLogout }}",
        "{{ yahooLinked }}",
        "{{ yahooApi }}",
        "{{ yahooStateLabel }}",
        "{{ onYahooApi }}",
    ):
        assert binding not in served, binding


def test_the_absence_explains_itself(index_html):
    """Deleted outright, the panel simply vanishes and reads as a bug to
    anyone who saw it last week. One line answers "why is there no Yahoo
    here" so the app does not leave that question hanging."""
    served, _ = page.apply(index_html, page.PRE)

    assert "fantasy-access approval" in served


def test_the_server_side_yahoo_route_is_untouched():
    """Only the UI comes off. Approval means putting the panel back, not
    rebuilding the OAuth flow."""
    from app.routes import auth

    assert any("/auth/yahoo" in getattr(r, "path", "") for r in auth.router.routes)


# --- the Sleepers tab's own list ---------------------------------------


def test_the_sleepers_tab_offers_a_list_of_your_own(index_html):
    """Owner, Aug 25: "this list should be editble like we discused".

    The tab was 19 rows transcribed from other people's previews on Aug
    14 and frozen. The transform's whole job is to open the door for a
    per-user list, so what it must leave behind is the anchor mobile.js
    builds into -- above the frozen table, not below it."""
    served, misses = page.apply(index_html, page.PRE)

    assert misses == []
    assert "data-fb-sleepers" in served
    assert served.index("data-fb-sleepers") < served.index("{{ showSleeperTable }}")


def test_the_analysts_table_is_named_rather_than_deleted(index_html):
    """19 researched names are a reasonable place to start a list from --
    the failure was that they were the *only* list. Kept, but labelled,
    so the two panels cannot be read as one."""
    served, _ = page.apply(index_html, page.PRE)

    assert "hand-read, not live" in served
    assert "{{ targets }}" in served


def test_a_missing_table_anchor_reports_a_miss(index_html):
    """Insert nothing, say so. A watchlist anchor that silently failed to
    land renders as a tab that simply has no list on it."""
    stripped = index_html.replace("{{ showSleeperTable }}", "{{ gone }}")

    served, misses = page.sleepers_watchlist(stripped)

    assert misses == ["sleepers watchlist anchor"]
    assert served == stripped


# --- one wire, one name ----------------------------------------------------


def test_the_second_door_into_the_same_feed_is_closed(index_html):
    """Owner, Aug 26: "news and post and alerts are same thing stay with
    alerts". The Alerts screen already concatenated the live wire onto the
    curated calls, so "News & posts" was a second entry into items it was
    showing anyway."""
    served, misses = page.apply(index_html, page.PRE)

    assert misses == []
    assert 'label: "News & posts"' not in served
    assert 'id: "alerts", label: "Alerts"' in served


def test_the_alerts_badge_counts_what_is_really_there(index_html):
    """It was the hardcoded string "6" — the curated rows alone. A badge
    that under-reports by two orders of magnitude is not cosmetic: it is
    the number a reader uses to decide whether to open the tab, and it was
    telling them not to bother."""
    served, _ = page.apply(index_html, page.PRE)

    assert 'badge: "6"' not in served
    assert "String(ALERTS.length + NEWS.length)" in served


def test_the_kicker_stops_describing_only_the_curated_half(index_html):
    """The live wire is what fills this screen. Saying so is how a reader
    knows it is worth refreshing."""
    served, _ = page.apply(index_html, page.PRE)

    assert "The live wire and your own calls" in served
    assert "Camp status changes across the whole player pool" not in served


def test_a_named_publisher_is_not_a_third_synonym(index_html):
    """NBC player news stays. It is a real cut of the wire with editorial
    blurbs a headline cannot replace — not another word for the same
    list."""
    served, _ = page.apply(index_html, page.PRE)

    assert 'label: "NBC player news"' in served


def test_the_group_no_longer_calls_the_feed_news(index_html):
    """The sidebar heading was the last place the old word survived, and a
    heading is the first thing read."""
    served, _ = page.apply(index_html, page.PRE)

    assert "News & status" not in served
    assert "Alerts & status" in served


# --- back goes where you came from -----------------------------------------


def test_the_way_back_returns_to_the_tab_you_came_from(index_html):
    """Owner, Aug 26: "i should go back to the previous page im at right
    now i go bak to main alerts page that doesnt help". The control was
    bound to a handler hardcoded to `screen: "alerts"`."""
    served, misses = page.apply(index_html, page.PRE)

    assert misses == []
    assert 'screen: "alerts", player: null' not in served
    assert 'screen: this.state.lastNav || "alerts", player: null' in served


def test_the_button_stops_naming_a_destination_it_does_not_go_to(index_html):
    """It read "Back to alerts" while going to alerts from everywhere —
    honest but useless. Now the label is derived from the same `titles`
    map the header reads, so it cannot disagree with the click."""
    served, _ = page.apply(index_html, page.PRE)

    assert ">Back to alerts</button>" not in served
    assert ">{{ backLabel }}</button>" in served
    assert "backLabel:" in served


def test_only_sidebar_tabs_are_remembered(index_html):
    """Not every transient sub-screen. Being returned to a player detail
    you already left would be its own kind of wrong."""
    served, _ = page.apply(index_html, page.PRE)

    assert "this.setState({ screen: n.id, lastNav: n.id })" in served
    # The player-detail transitions stay plain `screen:` sets.
    assert 'screen: "player", player:' in served


def test_the_app_reopens_on_the_tab_you_were_last_using(index_html):
    """The other half of the same complaint: every served page's only way
    home is `/app/`, and `/app/` opened on the default tab."""
    served, _ = page.apply(index_html, page.PRE)

    assert 'localStorage.setItem("ww_screen", n.id)' in served
    assert 'const sc = localStorage.getItem("ww_screen")' in served


def test_the_remembered_tab_stays_on_the_device(index_html):
    """A cursor, not a list. A phone and a laptop can be in different
    places, so this is one of the keys `prefs` deliberately does not
    carry to the account."""
    from app.feeds import prefs

    assert "ww_screen" not in prefs.MANAGED


def test_a_missing_anchor_leaves_the_page_alone(index_html):
    """Five edits, all or none. A label rewired without its action would
    promise a destination the click does not go to."""
    for gone in (
        'backToAlerts: () => this.setState({ screen: "alerts", player: null }),',
        ">Back to alerts</button>",
        "onClick: () => this.setState({ screen: n.id })",
    ):
        broken = index_html.replace(gone, "/* moved */", 1)
        assert broken != index_html, f"anchor not in the page: {gone}"

        served, misses = page.back_where_you_were(broken)

        assert misses, gone
        # And nothing else was written either. `_apply` would have applied
        # the surviving four; these five are halves of one promise.
        assert served == broken, gone
