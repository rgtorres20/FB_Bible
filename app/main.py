"""Fantasy Sports Bible Phase 2 -- the Yahoo league link server.

Runs two ways from the same module, deliberately:
  * local / container:  uvicorn app.main:app --reload
  * Vercel serverless:  api/index.py imports `app`
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import leagues
from .config import get_settings
from .feeds import (
    board,
    clock,
    curated,
    depth,
    gamestack,
    injury,
    page,
    prefs,
    previews,
    projections,
    ranklists,
    scorecard,
    skin,
    stats,
    vegas,
    watchlist,
)
from .feeds import players as players_mod
from .feeds.store import FeedStore, StoredDataUnreadable
from .routes import access, auth, feeds, league, leaguecfg, userdata

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
_FRONTEND_INDEX = _FRONTEND_DIR / "index.html"

# index.html is a Claude Design (.dc) document: it loads ./support.js and a
# _ds/ bundle at runtime. Serving it without those renders a blank page, which
# is worse than an honest 404 -- so the mount requires the whole set.
_FRONTEND_RUNTIME = (
    _FRONTEND_DIR / "support.js",
    _FRONTEND_DIR / "manifest.webmanifest",
    _FRONTEND_DIR / "_ds",
)
_FRONTEND_MISSING = [p.name for p in (_FRONTEND_INDEX, *_FRONTEND_RUNTIME) if not p.exists()]
_FRONTEND_READY = not _FRONTEND_MISSING

settings = get_settings()
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)

app = FastAPI(
    title="Fantasy Sports Bible -- Yahoo league link",
    description=(
        "Phase 2 of the Fantasy Bible productization plan: OAuth to the Yahoo "
        "Fantasy API for live rosters, draft results and opponent picks."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(league.router)
app.include_router(feeds.router)
app.include_router(access.router)
app.include_router(userdata.router)
app.include_router(leaguecfg.router)


@app.exception_handler(StoredDataUnreadable)
async def _stored_data_unreadable(request: Request, exc: StoredDataUnreadable) -> JSONResponse:
    """An encrypted blob would not open. Answer with the cause.

    Registered once rather than caught at each of the thirty-odd load
    call sites, so a route added later inherits it. 503 and not 500
    because the deployment is misconfigured, not the request: the blob is
    intact and a restored TOKEN_ENCRYPTION_KEY fixes it. The same
    reasoning as the named 503 `deps.get_store` gives a missing setting --
    a bare 500 sends the owner to Vercel's logs to learn something the
    response could say.

    The message names the variable, never its value.
    """
    logging.getLogger(__name__).error("%s unreadable: %s", exc.what, exc)
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                f"The stored {exc.what} could not be read. This is what a "
                "changed or missing TOKEN_ENCRYPTION_KEY looks like -- the "
                "data itself is intact and restoring the key restores it. "
                "Nothing has been overwritten."
            )
        },
    )


@app.middleware("http")
async def app_access_gate(request: Request, call_next):
    """The login gate for everything under /app (owner request, Aug 20).

    Inert until the owner enables it fully in Vercel env (APP_AUTH=on +
    OWNER_EMAIL + APP_OWNER_CODE + a real SESSION_SECRET — docs/ACCESS.md);
    a partial enable stays open rather than locking the owner out, and
    /health says which state it's in. /login, /health, the API and the
    Yahoo OAuth callbacks stay outside the gate; the sync runner and the
    watchdog pass with the X-Sync-Token they already hold.
    """
    s = get_settings()
    path = request.url.path
    in_app = path == "/app" or path.startswith("/app/")
    # The sign-in page is public but its artwork is not, and that is
    # a contradiction the gate used to enforce: /login rendered fine
    # while the mark, the favicon and the theme stylesheet all came
    # back 401, because every one of them lives under /app. The page
    # looked broken to exactly the people it exists for -- anyone not
    # signed in yet.
    #
    # A tight allowlist rather than "static files are public": these
    # four carry brand art and colour tokens and no user data of any
    # kind. Everything else under /app stays behind the gate.
    public_asset = (
        path.startswith(("/app/assets/", "/app/icons/"))
        or path == "/app/teams.css"
        or path == "/app/manifest.webmanifest"
    )
    if s.app_auth_enabled and in_app and not public_asset:
        if not await access.request_allowed(request, s):
            # no-store here too: a cached copy of this refusal would keep
            # turning away signed-in readers for as long as it lived.
            if "text/html" in request.headers.get("accept", ""):
                return RedirectResponse(
                    "/login", status_code=303, headers={"Cache-Control": "no-store"}
                )
            return JSONResponse(
                {"detail": "sign-in required"},
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )
    response = await call_next(request)
    # Everything gated is also uncacheable (Sep 1). These responses carried
    # no Cache-Control at all, which leaves the caching decision to whoever
    # sits in the path -- and production sits behind Cloudflare's proxy
    # (docs/PRODUCTIZE.md records the orange-cloud divergence), with the
    # browser's own heuristics behind that. A cached copy of the app page
    # or feeds.json is one reader's old wire served to whoever the cache
    # covers, wearing this morning's URL; the page then renders its Aug-14
    # seeds and every tab looks dead while the server is fresh. no-store is
    # the header that says this answer was for this request only. The four
    # public brand assets stay cacheable -- teams.css already declares its
    # own hour, and none of them carries user data or freshness claims.
    if in_app and not public_asset and "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    """Send the bare domain to the app.

    Without this the root returns a JSON 404, which reads as "nothing on
    screen" to anyone who types the domain without remembering /app/ --
    including the person who owns it.
    """
    return RedirectResponse("/app/" if _FRONTEND_READY else "/docs")


@app.get("/health", tags=["meta"], summary="Liveness plus configuration state")
async def health(
    store: FeedStore | None = Depends(feeds.get_optional_feed_store),
) -> dict:
    """Deliberately reports config problems rather than just 'ok', so a bad
    deploy is visible without reading logs.

    Since Aug 22 it also reports the player index. That outage showed up
    as four unrelated boards coming back empty with nothing naming the
    cause -- it is one store key, and one request should say so.
    """
    # Never let a store problem take /health down: it is the endpoint you
    # reach for *because* something is wrong.
    index_state: dict = {"count": None, "age_hours": None}
    if store is not None:
        try:
            index = await store.load_players()
            age = players_mod.age_seconds(index)
            index_state = {
                "count": len((index or {}).get("players") or {}),
                "age_hours": round(age / 3600, 1) if age is not None else None,
                # The reason, not just the symptom. An empty index showed
                # up as four unrelated empty boards with no cause
                # reachable from outside Vercel's own logs.
                "last_error": (await store.load()).get("index_error"),
                # Names more than one active player answers to. The
                # winner is a rank tie-break rather than dump order
                # (Aug 26), and this is how a reader outside Vercel's
                # logs can tell the stored index carries that rule at
                # all -- an older blob simply has no such key.
                "shared_names": len((index or {}).get("shared_names") or [])
                if index and "shared_names" in index
                else None,
            }
        except Exception as exc:  # noqa: BLE001 - report the gap, never raise
            logging.getLogger(__name__).warning("health: player index unreadable: %s", exc)
    return {
        "status": "ok",
        "stage": settings.stage,
        # The input the stage fallback reads. Reported because the fallback
        # can go quiet in exactly one way -- a Vercel project with system
        # environment variables not exposed hands the function no ref -- and
        # an empty string here says so in one request instead of a guess.
        "branch": settings.vercel_git_commit_ref,
        "yahoo_configured": settings.configured,
        "app_auth": settings.auth_state,
        # Whether invite mail can actually send. Reported rather than
        # assumed: an unconfigured SMTP is a silent no-op from the
        # outside, and "I never got one" should be answerable in one
        # request instead of a guess (docs/ACCESS.md).
        "invite_email": settings.mail_transport,
        "token_store": settings.token_store,
        "encryption_configured": bool(settings.token_encryption_key),
        # How the two blobs worth stealing are written: the access list
        # (password hashes) and each person's own layer (documents,
        # ranking lists, league settings). Both use the key above, so one
        # field covers both -- and it is named for the data rather than
        # for `auth` alone, because a field called auth_at_rest reporting
        # on somebody's saved documents is a mislabel, which is the same
        # fault as a real number under a "Proj" header.
        #
        # Reported rather than assumed for the same reason as
        # invite_email: with no key the store falls back to plaintext,
        # which is a real downgrade and is invisible from outside.
        "stored_data_at_rest": ("encrypted" if settings.token_encryption_key else "plaintext"),
        "league_keys": settings.league_keys,
        "frontend_ready": _FRONTEND_READY,
        "frontend_missing": _FRONTEND_MISSING,
        # How many players the boards can see, and how long since Sleeper
        # last answered. A count of 0 is the Aug 22 incident; a rising age
        # with a healthy count is the carry-forward working.
        "players": index_state,
    }


# --- The app itself -------------------------------------------------------
# Serving the page from the same origin as the API is deliberate: it makes
# CORS a non-issue, puts the whole thing on one URL you can open on a phone,
# and means one deploy rather than two.
#
# Mounted last so /health, /api/* and /auth/* still win. Mounted at /app
# rather than / so it cannot shadow them by accident.
#
# index.html and its data/icons are in the repo, but the Claude Design runtime
# it loads (support.js, manifest.webmanifest, _ds/) is not yet -- so the mount
# stays off and /app 404s rather than serving a page that renders blank.
# /health lists exactly what is missing. See docs/MIGRATION.md.
if _FRONTEND_READY:

    @app.get("/app/", include_in_schema=False)
    @app.get("/app/index.html", include_in_schema=False)
    async def app_page(
        request: Request,
        store: FeedStore | None = Depends(feeds.get_optional_feed_store),
        settings=Depends(get_settings),
    ) -> HTMLResponse:
        """Serve the page with the mobile stylesheet injected.

        index.html stays byte-identical on disk (see the no-fork note above);
        the <link> exists only in the served response, the same way the live
        feeds overlay works for data. Registered before the mount, so it wins
        for these two paths while every other asset stays static.
        """
        html = _FRONTEND_INDEX.read_text(encoding="utf-8")
        log = logging.getLogger(__name__)
        # A player listed twice on the board shows up twice mid-draft, and
        # marking one row taken leaves the other looking available. Not
        # gated on the store: this is wrong with or without live ADP.
        html, deduped = board.dedupe(html)
        if deduped:
            log.info("board: dropped duplicate rows for %s", deduped)
        # Every other edit to the served page is a named transform owned by
        # app/feeds/page.py. It reports the anchors it could not find, so a
        # design resync that renames a literal says so instead of quietly
        # dropping a feature -- a silent html.replace() miss is the same
        # failure as a control wired to nothing.
        html, misses = page.apply(html, page.PRE)
        if misses:
            log.warning("served page: transforms found no anchor for %s", ", ".join(misses))
        # Live overlays, every failure path serving the committed page: the
        # odds caption stops claiming openers, TD-lean confidence tracks
        # implied-total movement (the leans stay the owner's), the Week 1
        # schedule swaps in real kickoffs once the pushed slate carries them,
        # and the draft board's ADP column becomes real ADP. The board is
        # deliberately outside the odds check -- it rides the ADP feed, which
        # is fetched by the deployment itself and fails independently.
        if store is not None:
            try:
                stored = await store.load()
                # Loaded here rather than beside board.decorate because two
                # consumers now join on it: the board's decorations below,
                # and the TD-lean forecast clauses joined by player id.
                index = await store.load_players()
                state = stored.get("vegas") or {}
                games = state.get("games") or []
                if games:
                    html = vegas.refresh_caption(html, state)
                    adjusted = vegas.adjust_predictions(
                        vegas.curated_predictions(),
                        vegas.curated_implied(),
                        vegas.implied_by_team(games),
                    )
                    # The owner's leans, confidence tracking the live line,
                    # a labelled AI clause where one was drafted, and
                    # Rotowire's Week 1 TD forecast where Sleeper carries
                    # one (owner's FFBets flag, Aug 21; STALE_DATA #7).
                    adjusted = vegas.apply_reviews(adjusted, stored.get("pred_reviews"))
                    adjusted = vegas.apply_forecasts(
                        adjusted,
                        projections.td_forecasts(
                            stored.get("week_projections"),
                            adjusted,
                            scorecard.name_index(index),
                        ),
                    )
                    # The Predictions tab's "more active" half (owner, Sep 3):
                    # the newest wire item tagging the man and Sleeper's
                    # current flag, then the line beside Rotowire's projected
                    # team TDs and any starter out on that team with the next
                    # man's own projection. Four more labelled clauses; the
                    # lean and the confidence stay the owner's.
                    lean_names = tuple(p["name"] for p in adjusted)
                    adjusted = vegas.apply_forecasts(
                        adjusted,
                        injury.lean_clauses(stored.get("items", []), index, lean_names),
                    )
                    stack = gamestack.build(
                        state,
                        stored.get("week_projections"),
                        index,
                        stored.get("stats"),
                        stored.get("items", []),
                        leagues.defaults(),
                    )
                    adjusted = vegas.apply_forecasts(
                        adjusted,
                        gamestack.lean_clauses(
                            stack,
                            adjusted,
                            gamestack.vacancies(
                                index,
                                stored.get("stats"),
                                stored.get("week_projections"),
                                leagues.defaults(),
                            ),
                        ),
                    )
                    html = vegas.inject_predictions(html, adjusted)
                    html = vegas.inject_schedule(
                        html,
                        vegas.schedule_rows(
                            state,
                            previews=previews.by_matchup(state, stored.get("previews")),
                        ),
                        vegas.central_stamp(state.get("fetched_at")),
                    )
                # The Draft analyzer's ADP column, joined from the live
                # blend. Uncovered players show a dash rather than the
                # derived round.pick number they used to show.
                html, covered = board.inject(html, (stored.get("adp") or {}).get("state"))
                if covered:
                    logging.getLogger(__name__).info("board: %d rows carry live ADP", covered)
                # The design document ships 205 rows against a 300-pick draft
                # that starts 96 individual defenders, so the board could not
                # seat the starting lineups (docs/BOARD_EXPECTED.md). Depth
                # comes from the live player index, marked as index depth
                # rather than given an invented scouting note.
                # Who is on the board, then what the rows say about
                # them -- `board.decorate` owns that order and explains
                # why. Both decorations are name-keyed maps, so one built
                # before `drop_reserve` leaves keys pointing at players
                # who are gone, and one built before `deepen` never
                # reaches the third of the board that gets appended.
                # Both were true until the live watchdog said so.
                # '26 projections, when the sync has them (owner, Aug 25:
                # "yes lets add real projections"). The board's numeric
                # column reads them under the picked league's own scoring,
                # and falls back to last season's measured line -- with a
                # header that says which -- when it does not.
                html, marks = board.decorate(
                    html,
                    index,
                    stored.get("stats"),
                    leagues.defaults(),
                    stored.get("projections"),
                )
                if marks["projected"]:
                    log.info("board: points column reads '26 projections")
                # The handcuff table's usage splits, measured rather than
                # guessed (owner, Aug 25). depth.usage() has computed the
                # real ones for /app/nextup since Aug 21 and nothing had
                # joined them to this table -- STALE_DATA has named it the
                # remaining step ever since.
                #
                # Its own guard, and that is the lesson rather than the
                # feature: this raised on Aug 26 (it read `by_name` as
                # records when it maps to ids) and, sharing one
                # `except Exception` with everything below, silently took
                # the Team-intel usage read down with it. One overlay
                # failing must cost one overlay.
                try:
                    html, n_cuffs = depth.inject_cuffs(html, index, stored.get("stats"))
                    if n_cuffs:
                        log.info("board: %d handcuff rows measured", n_cuffs)
                except Exception:
                    log.exception("handcuff usage: not injected, table keeps its own numbers")
                if marks["benched"]:
                    log.info(
                        "board: dropped %d players on a reserve list: %s",
                        len(marks["benched"]),
                        ", ".join(marks["benched"][:5]),
                    )
                if marks["deepened"]:
                    log.info("board: appended %d rows of index depth", marks["deepened"])
                if marks["scored"]:
                    log.info(
                        "board: %d players carry league-scored points per game",
                        marks["scored"],
                    )
                if marks["flagged"]:
                    log.info("board: %d players carry a live injury flag", marks["flagged"])
                # Team-intel usage reads: the measured '25 pass rate and
                # red-zone run share replace the curated estimates, labelled
                # as such -- all 32 teams or nothing (see stats.usage_reads).
                try:
                    html, intel_live = stats.inject(html, stored.get("stats"))
                    if intel_live:
                        log.info("team intel: usage reads live from Sleeper '25 aggregates")
                except Exception:
                    log.exception("team intel: not injected, tab keeps its curated estimates")
            except Exception:  # noqa: BLE001 - overlays must never blank the page
                # `exception`, not `warning`: the Aug 26 regression logged
                # one line of exception text with no location, and the
                # only reason it was found at all is that the live
                # watchdog reads three separate surfaces.
                log.exception("live page overlays unavailable")
        # The blend's inputs, published so the Draft analyzer can show how
        # its average is built (owner, Aug 21). Outside the store block on
        # purpose: these lists are committed data, so the panel is right
        # even when every live feed is down -- and a panel that vanishes
        # exactly when the board falls back is the worst time to lose the
        # explanation of what the board is ordered by.
        mine: list[ranklists.RankList] = []
        who = access.session_email(request, settings)
        user_data: dict = {}
        if who and store is not None:
            try:
                user_data = await store.load_user(who)
                mine = ranklists.user_lists(user_data)
            except Exception as exc:  # noqa: BLE001 - the committed lists still stand
                log.warning("ranking sources: user lists unavailable: %s", exc)
        # The draft analyzer's league picker. The page shipped with the
        # design document's two leagues hardcoded, so the third verified
        # one was invisible there and a league defined at /app/leagues
        # never appeared at all (owner, Aug 25 -- two reports, one cause).
        # Read from the signed-in user's own settings, falling back to the
        # verified defaults, exactly like every other league-aware surface.
        html, n_lg = board.inject_leagues(html, leagues.for_user(user_data))
        if n_lg:
            log.info("board: %d leagues in the analyzer", n_lg)
        else:
            log.warning("board: league picker anchors not found -- still the hardcoded two")
        # One sleepers list, not two (owner, Aug 26). The page's own stars
        # wrote to localStorage while the Sleepers panel wrote to the
        # server, so starring a player did not put him on the list the
        # panel showed. Only for a signed-in reader: without an account
        # there is no server list, and `None` leaves the stars exactly as
        # the design document shipped them.
        html, n_slp = board.inject_sleepers(
            html, watchlist.watched(user_data) if who and store is not None else None
        )
        log.info("board: sleeper stars wired to the server list (%d on it)", n_slp)
        # The user's own on/off choices, over both populations. Applied
        # HERE as well as in the JSON endpoint, and that is the point: the
        # panel and the blend have to read the same set, or the board
        # averages a list the panel is showing as switched off.
        # Who this page belongs to, in its own header. Every board below
        # is per-user now -- league settings, ranking lists, which lists
        # count -- so "whose account is this" is a live question and had
        # no answer on the main screen.
        html, _ = page.header_identity(html, who)
        # The reader's own lists follow their account rather than their
        # browser (owner, Aug 26: "when i log into other devices i dont
        # see my changes"). Injected before </head>, which is before the
        # page's own script reads those keys -- later would already have
        # missed the read that decides what the first screen shows.
        html, prefs_misses = page.prefs_shim(
            html, prefs.stored(user_data) if who and store is not None else None
        )
        if prefs_misses:
            log.warning("served page: prefs shim found no anchor for %s", prefs_misses)
        # The two hand-read tabs say how old they are (owner, Aug 25:
        # "we need to add dates so i know if this is latest or
        # preseason"). Neither said anything about its own age, and both
        # had stood since Aug 14 -- through a round of preseason games.
        html, n_dated = curated.inject(html, clock.today())
        if n_dated != 2:
            log.warning("curated stamps: %d of 2 tabs dated", n_dated)
        every = ranklists.with_overrides(ranklists.builtins() + mine, user_data)
        html, n_src = board.inject_sources(html, ranklists.sources_payload(every, clock.today()))
        if n_src:
            log.info("board: %d ranking sources published", n_src)
        html, post_misses = page.apply(html, page.POST)
        if post_misses:
            log.warning("served page: transforms found no anchor for %s", ", ".join(post_misses))
        if settings.stage == "preview":
            html, _ = page.stage_badge(html)
        return HTMLResponse(html)

    # A trailing slash used to be a 404 on every one of these (owner, Aug
    # 25: "mystuff not working -- not found").
    #
    # Starlette redirects /path/ to /path when nothing matches, but the
    # StaticFiles mount below matches the /app PREFIX, so /app/mine/ is a
    # match -- handled by StaticFiles, which has no such file and answers
    # 404. The redirect never gets a chance. And /app/ itself is a real
    # page, so people are actively taught to type the slash.
    #
    # Registered BEFORE the mount, and generated from skin.SERVED_PAGES
    # rather than listed again, so a page added there inherits this
    # instead of shipping with the same 404.
    for _page in skin.SERVED_PAGES:

        def _slash_redirect(_target: str = _page) -> RedirectResponse:
            # 307, not 308: permanent is cacheable forever by the browser,
            # and this app is young enough to still move a path.
            return RedirectResponse(_target, status_code=307)

        app.get(_page + "/", include_in_schema=False)(_slash_redirect)

    app.mount("/app", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
