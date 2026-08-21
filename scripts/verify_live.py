"""Live-production verification: everything fixed must stay fixed.

CI proves the code; this proves the deployment. It runs on a schedule from
GitHub Actions and asserts against the real site, so a regression emails the
owner instead of waiting to be noticed in the app -- the failure mode this
project exists to kill is exactly "looked fine, was stale".

stdlib only: the job should never fail because of its own dependencies.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

# Run as a script from anywhere; the canonical page list lives in the app.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.feeds import skin  # noqa: E402

# Overridable so the same 35 checks can be pointed at a preview deployment.
# `or` rather than a get() default: an unset workflow input arrives as an
# empty string, which must not silently blank the URL.
BASE = os.environ.get("FBBIBLE_BASE") or "https://fb-bible-torro2.vercel.app"

# The cron is configured every 15 minutes but GitHub delivers roughly hourly
# on free public repos; three hours means "genuinely broken", not "jittery".
MAX_FEED_AGE = timedelta(hours=3)

failures: list[str] = []
passes: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    (passes if ok else failures).append(f"{label}{': ' + detail if detail else ''}")
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{': ' + detail if detail else ''}")


# Passes the /app login gate once the owner enables it; blank means the
# watchdog checks the open app exactly as before. Never printed.
_SYNC_TOKEN = os.environ.get("FBBIBLE_SYNC_TOKEN", "")


def get(path: str) -> bytes:
    headers = {"User-Agent": "FBBible-verify/1.0"}
    if _SYNC_TOKEN:
        headers["X-Sync-Token"] = _SYNC_TOKEN
    req = urllib.request.Request(BASE + path, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def get_json(path: str) -> dict | list:
    return json.loads(get(path))


def post_json(path: str) -> tuple[int, dict]:
    """(status, body) for an anonymous POST. Used to prove an endpoint is
    actually wired -- a missing dependency in the deployed bundle shows up
    here as a 500 rather than as a button that fails in someone's hand."""
    req = urllib.request.Request(
        BASE + path,
        data=b"",
        headers={"User-Agent": "FBBible-verify/1.0", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {}
    except Exception:  # noqa: BLE001 - a malformed body is still "not wired"
        return 0, {}


def anon_status(path: str) -> int:
    """Status code for a request carrying NO sync token, redirects not
    followed -- the only way to prove the login gate actually closes for
    a stranger rather than merely reporting that it is on."""

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):  # noqa: D102
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "FBBible-verify/1.0"})
    try:
        with opener.open(req, timeout=60) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def main() -> int:
    print(f"verifying {BASE} at {datetime.now(UTC).isoformat()}\n")

    # --- server configuration ---------------------------------------------
    health = get_json("/health")
    check("health.status", health.get("status") == "ok")
    check("health.token_store is redis", health.get("token_store") == "redis")
    check("health.encryption configured", health.get("encryption_configured") is True)
    check("health.frontend ready", health.get("frontend_ready") is True)
    # Reported, not asserted -- the same run has to serve both stages. What
    # matters is that a preview says "preview": that is what raises the BETA
    # badge, and a preprod indistinguishable from prod is how you edit the
    # wrong one during a draft.
    stage = health.get("stage", "?")
    print(f"  INFO  stage: {stage}  branch: {health.get('branch') or '(none reported)'}")
    if stage == "preview":
        served_early = get("/app/").decode("utf-8", errors="replace")
        check("preview wears the BETA badge", 'id="fb-stage-badge"' in served_early)

    # --- the news pipeline actually updates -------------------------------
    feeds = get_json("/api/feeds?limit=1")
    check("feed has items", feeds.get("total", 0) > 50, f"total={feeds.get('total')}")

    polled = feeds.get("polled_at")
    age = None
    if polled:
        age = datetime.now(UTC) - datetime.fromisoformat(polled)
    check(
        "feed polled recently",
        age is not None and age < MAX_FEED_AGE,
        f"age={age}" if age else "no polled_at",
    )

    sources = feeds.get("sources", {})
    check("all sources present", len(sources) >= 6, f"got {len(sources)}")
    for key, status in sorted(sources.items()):
        check(f"source {key} not FAILED", status.get("state") != "FAILED", status.get("state", "?"))

    # --- what the page actually receives ----------------------------------
    page_data = get_json("/app/data/feeds.json")
    check("page news is the live overlay", len(page_data.get("news", [])) > 25)
    # Newest first (owner request Aug 20): the wire entries' rendered times
    # must be non-increasing. Times carry no year, so pairs that cross a
    # month boundary are skipped rather than misjudged.
    wire_times = []
    for entry in page_data.get("news", []):
        if entry.get("kind") == "Wire" and entry.get("link") and entry.get("time"):
            try:
                wire_times.append(datetime.strptime(entry["time"], "%a %b %d · %I:%M %p"))
            except ValueError:
                pass
    in_order = all(
        a >= b for a, b in zip(wire_times, wire_times[1:], strict=False) if a.month == b.month
    )
    check("news reads newest first", bool(wire_times) and in_order, f"{len(wire_times)} stamps")
    check(
        "NBC tab carries live rows",
        any(
            str(entry.get("lean", "")).startswith("Auto:") or entry.get("link")
            for entry in page_data.get("rotowire", [])
        ),
    )
    meta = {m.get("feed"): m for m in page_data.get("meta", [])}
    news_as_of = meta.get("News & posts", {}).get("asOf", "")
    # asOf is naive Central ("2026-08-15T02:27"); yesterday's date means the
    # overlay stopped stamping. Central is UTC-5/6, so compare against a
    # generously-lagged UTC date rather than converting.
    lagged = f"{datetime.now(UTC) - timedelta(hours=30):%Y-%m-%d}"
    check("Data health stamp updates", news_as_of[:10] >= lagged, news_as_of)

    # Reported, not asserted. Verdicts are best-effort: the job exits 0 on a
    # rate limit or a missing key, so a zero hour is legitimate and failing
    # here would cry wolf. But a permanent break used to be invisible -- and
    # a sync bug silently deleted every verdict for a day before anyone
    # noticed -- so the count belongs in the log either way.
    drafted = sum(1 for e in page_data.get("news", []) if str(e.get("impact", "")).startswith("AI"))
    print(f"  INFO  AI-drafted verdicts on the news tab: {drafted}")

    # --- live draft-prep surfaces (Aug 15) ---------------------------------
    scout = page_data.get("scout", [])
    check(
        "Scout finds are live-generated",
        bool(scout)
        and any("FFC" in e.get("src", "") or "Sleeper rank" in e.get("src", "") for e in scout),
        f"{len(scout)} cards",
    )
    vegas_rows = page_data.get("vegas", [])
    check("Vegas slate present", len(vegas_rows) >= 8, f"{len(vegas_rows)} games")
    wk = page_data.get("weekrev") or {}
    check(
        "Week review carries live scores",
        len(wk.get("games") or []) >= 4 and bool(wk.get("stars")),
        wk.get("week_label") or wk.get("week") or "absent",
    )
    check(
        "Vegas slate marked live in Data health",
        "live" in meta.get("Vegas lines", {}).get("source", ""),
    )
    cheat = get("/app/cheatsheet").decode("utf-8", errors="replace")
    check(
        "cheat sheet serves the live board",
        "QBs above this market" in cheat and "Blend" in cheat,
    )

    # The top-300 alert board: one row per ranked player, wire-checked, with
    # machine lines labelled by author. Population needs the player index,
    # which the hourly sync keeps warm -- fewer than 250 rows means the
    # surface has degraded to its honest empty state.
    top300 = get("/app/alerts300").decode("utf-8", errors="replace")
    check("top-300 alert board serves", "Top-300 alert board" in top300)
    check(
        "top-300 board is populated",
        top300.count("<tr>") >= 250,
        f"{top300.count('<tr>')} rows",
    )
    check("top-300 board credits Sleeper", "data: Sleeper" in top300)
    drafted300 = top300.count("AI draft:")
    print(f"  INFO  AI-drafted lines on the top-300 board: {drafted300}")
    # Same best-effort rule as verdicts: the capsule and mover-read jobs
    # exit 0 on a rate limit or missing key, so zero is a legitimate hour --
    # but a silent wipe or a permanently dead job shows up as a count stuck
    # at zero, which is why the numbers belong in the log.
    angles = top300.count("AI angle:")
    print(f"  INFO  AI player capsules on the top-300 board: {angles}")

    # The IDP draft board: serving is asserted; population is reported --
    # it needs the index and stats refetches that follow a deploy, and its
    # empty states are honest about which piece is still missing.
    idp_page = get("/app/idp").decode("utf-8", errors="replace")
    check("IDP draft board serves", "IDP draft board" in idp_page)
    idp_rows = max(idp_page.count("<tr>") - 1, 0)
    print(f"  INFO  IDP board rows: {idp_rows}")
    reads = sum(1 for e in scout if "AI read:" in str(e.get("text", "")))
    print(f"  INFO  AI reads on the ADP mover cards: {reads}")

    # The scoring board (owner, Aug 21: "who would score the most points in
    # each league"). It is arithmetic over stored stats, so the failure
    # that matters is a table of zeroes -- which happens when the stored
    # blob predates the offensive fields and reads as a finding rather than
    # a gap. The page refuses to render one; this checks it did not have to.
    scoring_page = get("/app/scoring").decode("utf-8", errors="replace")
    check("scoring board serves", "Scoring board" in scoring_page)
    # `detail` prints on PASS as well as FAIL, so it has to describe what
    # was OBSERVED, never what failure would mean. A green line reading
    # "stored stats predate pass_cmp" is unreadable, and this log is the
    # thing CLAUDE.md says to read instead of the badge.
    stale_fields = "predate the scoring fields" in scoring_page
    check(
        "scoring board is not sitting on stale stat fields",
        not stale_fields,
        "stored stats predate pass_cmp -- the sync has not refetched" if stale_fields else "",
    )
    scoring_rows = max(scoring_page.count("<tr>") - 1, 0)
    check("scoring board is populated", scoring_rows > 0, f"{scoring_rows} rows")
    check(
        "scoring board says the numbers are not a projection",
        "not a projection" in scoring_page,
    )
    # The whole claim of the page: the columns differ because the leagues
    # do. Identical columns would mean the per-league scoring is not being
    # applied -- which would look completely normal on screen.
    #
    # Deduped, and GP excluded: the D/ST table repeats both, so the raw
    # match list read "GP, NDDPL, RED_EYE, BALLAPALOSA, GP, BALLAPALOSA"
    # and a reader cannot tell a repeated column from a duplicated league.
    per_league = sorted(
        {th for th in re.findall(r"<th>([A-Z_]+)</th>", scoring_page) if th != "GP"}
    )
    check(
        "scoring board carries a column per league",
        len(per_league) >= 2,
        ", ".join(per_league) or "none",
    )

    # The mock draft room: the page must serve with its embedded pool and
    # its honesty framing -- simulated picks are labelled, never sold as a
    # prediction of the real room.
    mock_page = get("/app/mock").decode("utf-8", errors="replace")
    check("mock draft room serves", "Mock draft room" in mock_page)
    check("mock room carries the live pool", "FB_MOCK" in mock_page)
    check("mock room labels its simulation", "Simulated picks are labelled" in mock_page)

    # The login gate: the page must serve, and /health must name the gate's
    # state -- "off" until the owner enables it, then "on"; a lingering
    # "misconfigured" is a half-enable worth seeing in the log.
    login_page = get("/login").decode("utf-8", errors="replace")
    served_login_probe = get("/app/").decode("utf-8", errors="replace")
    check("login page serves", "Owner sign-in" in login_page)
    check("login offers passkey sign-in", "Sign in with Face ID" in login_page)
    # Proves the WebAuthn dependency survived the deploy: this endpoint
    # imports it, so a bundle that dropped it answers 500 here instead of
    # failing later in someone's hand. The challenge must be real, too.
    code, opts = post_json("/passkey/login/options")
    check(
        "passkey challenge issues",
        code == 200 and len(str(opts.get("challenge", ""))) > 20,
        f"HTTP {code}",
    )
    gate = health.get("app_auth", "?")
    print(f"  INFO  app login gate: {gate}")
    # "http" works on Vercel; "smtp" is configured but will hang there.
    mail = health.get("invite_email", "?")
    print(f"  INFO  invite email transport: {mail}")
    if mail == "smtp" and stage != "local":
        print("  INFO  (SMTP cannot send from Vercel -- set RESEND_API_KEY)")
    if gate == "on":
        # Closed means closed: a stranger with no session and no sync
        # token must be turned away from the app itself, not merely told
        # the gate is on. 303 to /login (HTML) or 401 both count.
        code = anon_status("/app/")
        check("gate turns strangers away", code in (303, 401, 307), f"HTTP {code}")
    elif gate == "misconfigured":
        # Half-set enable: the app stays open by design, but the owner
        # meant to close it -- surface it rather than passing quietly.
        check("app_auth not half-configured", False, "APP_AUTH set without its companions")
    # The personal layer: anonymous (the watchdog has no session) must get
    # the honest ask-to-sign-in page, never someone's data.
    mine_page = get("/app/mine").decode("utf-8", errors="replace")
    check("my-stuff page serves", "My stuff" in mine_page)

    # The pickup board. It renders whatever the live injury flags say, so
    # an empty board is a legitimate answer -- what must never happen is
    # the page failing to serve, or serving without saying which half of
    # it is measured rather than live.
    nextup_page = get("/app/nextup").decode("utf-8", errors="replace")
    check("next-man-up board serves", "Next man up" in nextup_page)
    check(
        "next-man-up says which half is live",
        "Nothing here is projected" in nextup_page
        or "No starter is currently flagged out" in nextup_page,
    )
    flagged = nextup_page.count("class='row'")
    print(f"  INFO  starters flagged out right now: {flagged}")

    # The scorecard. Its whole value is that it refuses to show a number
    # it cannot back, so the check is that it never prints a rate before
    # there are graded games behind it.
    score_page = get("/app/scorecard").decode("utf-8", errors="replace")
    check("scorecard serves", "Scorecard" in score_page)
    ungraded = "Nothing recorded yet" in score_page or "Nothing graded yet" in score_page
    shows_rate = "hit rate" in score_page.lower()
    # The detail is neutral in both directions on purpose. Written as a
    # failure sentence it printed "printed a rate with nothing graded"
    # next to a PASS -- a green line that reads like a broken one, which
    # is the exact failure mode this whole watchdog exists to avoid.
    check(
        "scorecard shows a rate only when games are behind it",
        shows_rate != ungraded,
        f"rate shown: {shows_rate}; nothing graded: {ungraded}",
    )
    print(f"  INFO  prediction ledger graded yet: {'no' if ungraded else 'yes'}")

    # League settings: same rule as /app/mine -- the watchdog has no
    # session, so it must get the honest ask-to-sign-in page rather than
    # anybody's league. And the built-ins must still be described as the
    # owner's verified settings, not silently editable.
    # The mark. A favicon that 404s is invisible until someone bookmarks
    # the app, and the sign-in page is the one surface that has to
    # introduce the app to a stranger (docs/BRAND.md).
    check("sign-in page leads with the mark", "/app/assets/fsb-logo.svg" in login_page)
    check("sign-in page says what the app is", "What this is" in login_page)
    # Club themes. The stylesheet is linked by every page, so a 404 here
    # is 33 broken themes and a light-mode app (docs/BRAND.md).
    team_css = get("/app/teams.css").decode("utf-8", errors="replace")
    club_blocks = team_css.count('[data-theme="team"][data-team=')
    check("team themes serve", club_blocks >= 32, f"{club_blocks} palettes")
    check("no club picked still has a palette", ":not([data-team])" in team_css)
    check("app opens on the club theme", "'ww_theme')||'team'" in served_login_probe)

    icon = get("/app/assets/fsb-icon.svg").decode("utf-8", errors="replace")
    check("app icon serves", "</svg>" in icon)

    # Anonymously, which is the only way this means anything. Every check
    # above sends the sync token and therefore walks through the login
    # gate -- so they proved these files EXIST while a signed-out visitor
    # got 401 for the mark, the favicon and the theme stylesheet, and the
    # sign-in page rendered unstyled and logo-less for exactly the people
    # it is for. Existing is not the property that matters here; being
    # fetchable by someone who has not signed in is.
    for label, asset in (
        ("mark", "/app/assets/fsb-logo.svg"),
        ("favicon", "/app/assets/fsb-icon.svg"),
        ("theme stylesheet", "/app/teams.css"),
        ("home-screen icon", "/app/icons/icon-192.png"),
    ):
        code = anon_status(asset)
        check(f"sign-in page can load its {label}", code == 200, f"HTTP {code}")
    # And the allowlist must not have opened anything else.
    for guarded in (
        "/app/",
        "/app/mine",
        "/app/mobile.js",
        "/app/data/feeds.json",
        "/app/data/ranksources.json",
    ):
        code = anon_status(guarded)
        check(f"still gated: {guarded}", code in (303, 401, 307), f"HTTP {code}")
    check("app page carries the icon", "/app/assets/fsb-icon.svg" in served_login_probe)

    lg_page = get("/app/leagues").decode("utf-8", errors="replace")
    check("league settings page serves", "League settings" in lg_page)
    check(
        "league settings ask for a sign-in rather than guessing",
        "Sign in" in lg_page and "Add a league" not in lg_page,
    )
    # The boards fall back to the owner's verified two for a visitor with
    # no leagues of their own -- which is exactly what the watchdog is.
    check("IDP board keeps its verified columns", "NDDPL '25" in idp_page)
    check("mock room offers the verified leagues", '"NDDPL"' in mock_page)

    # Every board must offer a way back. In the installed PWA there is no
    # address bar, so a page whose only exit is a buried text link is a
    # dead end -- the owner hit exactly that after picking a club theme
    # (Aug 21). The unit test covers what the app RENDERS; this covers
    # what it actually SERVES, which is a different claim: a page can
    # render its bar and still be broken by a route or a gate.
    # The list lives in app/feeds/skin.py, which owns the home bar itself.
    # It used to be duplicated here, and on Aug 21 it drifted exactly as
    # you would expect: /app/scoring was added to the unit test's copy and
    # not to this one, so the new page rendered its way home and nothing
    # checked that it served one.
    for path in skin.SERVED_PAGES:
        page = get(path).decode("utf-8", errors="replace")
        check(
            f"way back to the app from {path}",
            "class='fsb-home' href='/app/'" in page,
        )
        # Owner, Aug 21: "my fab logo should be on all pages." Two
        # separate things -- the tab icon in the head and the mark the
        # home bar shows -- and the heads had drifted apart before they
        # were generated from one place.
        check(
            f"mark on {path}",
            "/app/assets/fsb-icon.svg" in page and "/app/assets/fsb-mark.svg" in page,
        )
        # Found while fixing the logo: three pages never read ww_theme,
        # so they ignored the club the user picked.
        check(f"{path} wears the picked theme", "ww_theme" in page)

    # Team defenses. The D/ST board only renders for a signed-in user
    # whose league starts a DEF slot, which the watchdog can never be --
    # so what it checks is the thing underneath: that the weekly stats
    # refetch actually stored the 32 team-defense lines, and that every
    # one of them carries a points-allowed ladder accounting for all its
    # games. Ranking from a partial ladder is the failure this guards.
    dst = json.loads(get("/api/defenses"))
    total, complete = dst.get("total", 0), dst.get("complete", 0)
    check("team defenses stored", total >= 32, f"{total} stored")
    check(
        "every defense has a full points-allowed ladder",
        total > 0 and complete == total,
        f"{complete} of {total}",
    )

    # --- the served page carries tonight's fixes --------------------------
    served = get("/app/").decode("utf-8", errors="replace")
    check("mobile stylesheet injected", 'href="mobile.css"' in served)
    # The mode picker is My team / Dark / Light now (owner, Aug 21). The
    # hand-written Cowboys and Titans options are gone on purpose -- they
    # were the first two of the 32 clubs and stopped being special.
    check(
        "mode picker offers My team, Dark and Light",
        '<option value="team">' in served
        and '<option value="dark">' in served
        and '<option value="light">' in served,
    )
    check("menu script injected", 'src="mobile.js"' in served)
    check("FFBets lands on Predictions", 'gdMode: "predict",' in served)
    # Strict on purpose: once the live board has shipped, a revert to the
    # curated openers means the odds pipeline is stale -- a true failure.
    check("vegas table rebound to live data", "vegas: (F.vegas || VEGAS)," in served)
    check("Vegas lines are live", "Live via ESPN" in served)
    check("TD leans track live lines", "confidence adjusted" in served)
    check("Week 1 schedule is live", "live kickoff times" in served)
    # Best-effort like every AI count: zero is a legitimate hour, a count
    # stuck at zero is the signal worth having in the log.
    game_previews = served.count("AI preview:")
    print(f"  INFO  AI matchup previews on the schedule tab: {game_previews}")
    # The draft board's ADP column: real numbers, and no consumer left
    # reading the old derived round.pick string.
    check("draft board carries live ADP", "const FB_LIVE_ADP = " in served)
    check("no consumer reads the derived ADP", "parseFloat(b.adp)" not in served)
    # Team-intel usage reads: measured '25 pass rate and red-zone run share
    # replace the curated estimates, and the label names the stat -- a
    # revert to "GL x% run" over estimates is the stale-data failure mode.
    check("Team intel usage reads are live", "FB live usage: Sleeper '25 season" in served)
    check("red-zone run share is labelled", "% run share ('25)" in served)
    # A player listed twice appears twice mid-draft, and marking one row
    # taken leaves the other looking available.
    rows = re.search(r"const RAW_BOARD = \[(.*?)\n\];", served, re.S)
    board_names = re.findall(r'^\s*\[\d+,"([^"]+)"', rows.group(1), re.M) if rows else []
    check(
        "board has no duplicate players",
        bool(board_names) and len(board_names) == len(set(board_names)),
        f"{len(board_names)} rows, {len(set(board_names))} distinct",
    )
    check("Build-a-team shelved", '{ id: "build", label: "Build a team" }' not in served)
    # The Trusted-sources panel, after the Aug 21 design resync. Five of
    # nine sliders used to move a bar and change no output; the panel now
    # renders a slider only for the rank lists and labels the other two
    # groups for what they are. A revert would not error -- it would just
    # start claiming influence again, which is why this is checked live.
    check("only the board-mix group gets a slider", "showSlider: board && on" in served)
    check(
        "source groups say what they do",
        '"not wired"' in served and '"on/off only"' in served,
    )
    # Two different things were called "sources" and the panel described
    # the wrong one. The four board sliders set one ratio; the real
    # ranking lists blend with no weights. A revert would not error -- it
    # would just start claiming to blend lists again.
    check(
        "board-mix group no longer calls itself a list blend",
        "Rank lists — draft board" not in served and "Each list's share blends" not in served,
    )
    check("board-mix group names what it actually sets", "Board order mix" in served)
    check(
        "analyzer slider stops promising named sources",
        "pure ESPN/Yahoo ADP blend" not in served,
    )

    # The one-time club ask. Owner, Aug 21: "choose your team should be in
    # middle of page so I can see it" -- it was a 12px strip on the bottom
    # edge among the sync footer and the menu button. A revert to that bar
    # is the failure this guards.
    ask_js = get("/app/mobile.js").decode("utf-8", errors="replace")
    check("club ask is a centred panel", "fb-team-ask-card" in ask_js)
    check("club ask asks the question in words", "Choose your team" in ask_js)

    # The Draft analyzer's source panel (owner, Aug 21: the list of lists
    # belongs in the analyzer "so they know how the average is created").
    # Three separate ways this goes quiet without erroring, so three
    # checks: the payload stops being injected, the endpoint that keeps it
    # current stops answering, or mobile.js loses the row it hangs off.
    sources = re.search(r"const FB_RANK_SOURCES = (\[.*?\]);\n", served, re.S)
    published = json.loads(sources.group(1)) if sources else []
    check(
        "rank sources published to the page",
        bool(published),
        f"{len(published)} lists, {sum(1 for x in published if x['active'])} in the blend",
    )
    check(
        "every published list carries its size and date",
        bool(published) and all(x.get("n") and x.get("asOf") for x in published),
    )
    live_sources = get_json("/app/data/ranksources.json")
    check(
        "ranksources.json answers",
        isinstance(live_sources, list) and bool(live_sources),
        f"{len(live_sources) if isinstance(live_sources, list) else 0} lists",
    )
    # The panel is built client-side, so a live page cannot prove it
    # rendered. What it can prove is that the script still carries the
    # anchor and the page still carries the row -- the pair that has to
    # survive a design resync.
    # Renamed at serve time; mobile.js anchors on the served text.
    check("analyzer keeps the row the panel hangs off", "Board order</span>" in served)

    mobile_css = get("/app/mobile.css")
    check("mobile.css serves", b"min-height: 100vh" in mobile_css)
    check("wire-stamp styles serve", b"fb-wire-stamp" in mobile_css)
    mobile_js = get("/app/mobile.js")
    check("mobile.js serves", b"fb-menu-btn" in mobile_js)
    check("overlay decorator serves", b"fb-new-badge" in mobile_js and b"injury_wire" in mobile_js)
    check(
        "source panel decorator serves",
        b"fb-rank-sources" in mobile_js and b"Board order" in mobile_js,
    )

    # --- verdict -----------------------------------------------------------
    print(f"\n{len(passes)} passed, {len(failures)} failed")
    if failures:
        print("\nFAILED checks:")
        for f in failures:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - a crashed check run must still fail loudly
        print(f"\nverification crashed: {type(exc).__name__}: {exc}")
        raise SystemExit(2) from exc
