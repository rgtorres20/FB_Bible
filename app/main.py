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

from .config import get_settings
from .feeds import board, previews, skin, stats, vegas
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
        store: FeedStore | None = Depends(feeds.get_optional_feed_store),
    ) -> HTMLResponse:
        """Serve the page with the mobile stylesheet injected.

        index.html stays byte-identical on disk (see the no-fork note above);
        the <link> exists only in the served response, the same way the live
        feeds overlay works for data. Registered before the mount, so it wins
        for these two paths while every other asset stays static.
        """
        html = _FRONTEND_INDEX.read_text(encoding="utf-8")
        html = html.replace(
            "</head>",
            '<link rel="stylesheet" href="mobile.css">'
            '<script src="mobile.js" defer></script>'
            # The brand mark, serve-time like everything else here, so a
            # design-project resync cannot drop it (docs/BRAND.md).
            f"{skin.FAVICON}"
            # The club palette, applied to <html> before first paint. The
            # page's own token blocks are [data-skin][data-theme] pairs
            # on its runtime's element; "team" matches none of them, so
            # these :root values inherit straight through instead of
            # fighting it (docs/BRAND.md).
            f"{skin.THEME_BOOT}</head>",
            1,
        )
        # FFBets, per the owner (Aug 15): Predictions is the landing mode and
        # the Build-a-team toggle is shelved for now. Both are serve-time
        # string edits -- the builder's code stays intact on disk and in git,
        # just unreferenced in the served copy, so restoring it is deleting
        # these two lines.
        # Vegas lines: rebind the committed VEGAS table to the fetched data
        # file, which the overlay route fills with live ESPN/DraftKings rows.
        # F is the parsed feeds.json in the enclosing scope; the `||` keeps
        # the committed table as the fallback when the overlay has no lines.
        # The dynamic imports carry the design project's layout
        # ("./frontend/lib/..."); served from /app/ the client lives at
        # ./lib/. Same class of fix sw.js already carries for its precache
        # list -- without this both the Yahoo link check and the 24h
        # yahoo-cache purge fail with "API client failed to load".
        html = html.replace('import("./frontend/lib/fbApi.js")', 'import("./lib/fbApi.js")')
        html = html.replace("vegas: VEGAS,", "vegas: (F.vegas || VEGAS),", 1)
        # A player listed twice on the board shows up twice mid-draft, and
        # marking one row taken leaves the other looking available. Not
        # gated on the store: this is wrong with or without live ADP.
        html, deduped = board.dedupe(html)
        if deduped:
            logging.getLogger(__name__).info("board: dropped duplicate rows for %s", deduped)
        html = html.replace('gdMode: "build",', 'gdMode: "predict",', 1)
        # The mode picker, rebuilt (owner, Aug 21): the user's club, Dark,
        # Light — with the club being whichever of the 32 they chose, and
        # the house navy until they choose one. Cowboys and Titans modes
        # were the first two of those 32; they are not special any more,
        # so the hand-written pair comes out and `data-team` decides.
        #
        # Serve-time string edits, like everything else here, so a design
        # resync that changes any of these literals misses cleanly and the
        # page keeps its own picker rather than breaking.
        html = html.replace(
            '<option value="cowboys">★ Cowboys mode</option>',
            '<option value="team">★ My team</option>',
            1,
        )
        # The label follows the same three values.
        html = html.replace(
            'themeLabel: s.theme === "cowboys" ? "★ Cowboys mode"',
            'themeLabel: s.theme === "team" ? "★ My team"',
            1,
        )
        # The restore guard whitelists stored themes. "team" joins it;
        # the two retired names stay accepted so a browser still holding
        # one is translated rather than reset (skin.THEME_BOOT does the
        # translating).
        html = html.replace(
            'if (th === "dark" || th === "light" || th === "cowboys")',
            'if (th === "dark" || th === "light" || th === "team" ||'
            ' th === "cowboys" || th === "titans")',
            1,
        )
        # The page's own skin hook. It only ever knew "cowboys"; the club
        # palettes come from /app/teams.css via data-team instead, so this
        # just stops the page forcing a Dallas skin on everyone.
        # Owner, Aug 21: "home page should be the dark blue not light
        # mode". The page's own default state was light; it opens on the
        # club theme now, which is the house navy until a club is picked.
        html = html.replace('theme: "light"', 'theme: "team"', 1)
        html = html.replace(
            'skin: "cowboys",',
            'skin: s.theme === "team" ? "team" : "none",',
            1,
        )
        html = html.replace(
            '[{ id: "build", label: "Build a team" }, { id: "predict", label: "Predictions" }]',
            '[{ id: "predict", label: "Predictions" }]',
            1,
        )
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
        # The app's wordmark in the sidebar. Serve-time like the rest, so
        # a design-project resync cannot silently revert the name.
        html = html.replace(">FANTASY BIBLE<", ">FANTASY SPORTS BIBLE<", 1)
        # The real league names (docs/LEAGUES.md, owner request): the design
        # document still says "Sunday Gravy" / "The Trenches" everywhere --
        # picker values, curated alert rows, helper copy, and the board's
        # injected ADP toggle. One late pass renames every occurrence, page
        # and injected snippets alike, so the picker values and the code
        # comparing against them move together. Full names first, then the
        # bare shorthands the curated copy uses.
        for old, new in (
            ("Sunday Gravy", "NDDPL"),
            ("The Trenches", "RED_EYE"),
            ("Gravy", "NDDPL"),
            ("Trenches", "RED_EYE"),
        ):
            html = html.replace(old, new)
        # A beta deploy announces itself (styles in mobile.css). Prod and
        # local runs serve no badge at all.
        if settings.stage == "preview":
            html = html.replace("</body>", '<div id="fb-stage-badge">BETA</div></body>', 1)
        return HTMLResponse(html)

    app.mount("/app", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
