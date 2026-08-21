"""Fantasy Sports Bible Phase 2 -- the Yahoo league link server.

Runs two ways from the same module, deliberately:
  * local / container:  uvicorn app.main:app --reload
  * Vercel serverless:  api/index.py imports `app`
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import leagues
from .config import get_settings
from .feeds import board, page, previews, ranklists, stats, vegas
from .feeds.store import FeedStore
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
    if s.app_auth_enabled and (path == "/app" or path.startswith("/app/")):
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
        if (
            path.startswith(("/app/assets/", "/app/icons/"))
            or path == "/app/teams.css"
            or path == "/app/manifest.webmanifest"
        ):
            return await call_next(request)
        if not await access.request_allowed(request, s):
            if "text/html" in request.headers.get("accept", ""):
                return RedirectResponse("/login", status_code=303)
            return JSONResponse({"detail": "sign-in required"}, status_code=401)
    return await call_next(request)


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    """Send the bare domain to the app.

    Without this the root returns a JSON 404, which reads as "nothing on
    screen" to anyone who types the domain without remembering /app/ --
    including the person who owns it.
    """
    return RedirectResponse("/app/" if _FRONTEND_READY else "/docs")


@app.get("/health", tags=["meta"], summary="Liveness plus configuration state")
async def health() -> dict:
    """Deliberately reports config problems rather than just 'ok', so a bad
    deploy is visible without reading logs."""
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
        "league_keys": settings.league_keys,
        "frontend_ready": _FRONTEND_READY,
        "frontend_missing": _FRONTEND_MISSING,
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
                state = stored.get("vegas") or {}
                games = state.get("games") or []
                if games:
                    html = vegas.refresh_caption(html)
                    adjusted = vegas.adjust_predictions(
                        vegas.curated_predictions(),
                        vegas.curated_implied(),
                        vegas.implied_by_team(games),
                    )
                    # The owner's leans, confidence tracking the live line,
                    # and a labelled AI clause where one was drafted.
                    adjusted = vegas.apply_reviews(adjusted, stored.get("pred_reviews"))
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
                html, deepened = board.deepen(html, await store.load_players(), leagues.defaults())
                if deepened:
                    logging.getLogger(__name__).info(
                        "board: appended %d rows of index depth", deepened
                    )
                # Team-intel usage reads: the measured '25 pass rate and
                # red-zone run share replace the curated estimates, labelled
                # as such -- all 32 teams or nothing (see stats.usage_reads).
                html, intel_live = stats.inject(html, stored.get("stats"))
                if intel_live:
                    logging.getLogger(__name__).info(
                        "team intel: usage reads live from Sleeper '25 aggregates"
                    )
            except Exception as exc:  # noqa: BLE001 - overlays must never blank the page
                logging.getLogger(__name__).warning("live page overlays unavailable: %s", exc)
        # The blend's inputs, published so the Draft analyzer can show how
        # its average is built (owner, Aug 21). Outside the store block on
        # purpose: these lists are committed data, so the panel is right
        # even when every live feed is down -- and a panel that vanishes
        # exactly when the board falls back is the worst time to lose the
        # explanation of what the board is ordered by.
        mine: list[ranklists.RankList] = []
        who = access.session_email(request, settings)
        if who and store is not None:
            try:
                mine = ranklists.user_lists(await store.load_user(who))
            except Exception as exc:  # noqa: BLE001 - the committed lists still stand
                log.warning("ranking sources: user lists unavailable: %s", exc)
        html, n_src = board.inject_sources(
            html, ranklists.sources_payload(ranklists.builtins() + mine, date.today())
        )
        if n_src:
            log.info("board: %d ranking sources published", n_src)
        html, post_misses = page.apply(html, page.POST)
        if post_misses:
            log.warning("served page: transforms found no anchor for %s", ", ".join(post_misses))
        if settings.stage == "preview":
            html, _ = page.stage_badge(html)
        return HTMLResponse(html)

    app.mount("/app", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
