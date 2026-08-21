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
            f"{skin.FAVICON}</head>",
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
        # Two team modes, owner's call (Aug 19): Cowboys stays exactly as
        # shipped, Titans joins beside it. The picker gains a fourth
        # option, the skin follows whichever starred mode is active, and
        # the titans token blocks live in mobile.css -- so a design resync
        # that changes any of these literals misses cleanly and the page
        # simply stays all-cowboys rather than breaking.
        html = html.replace(
            'skin: "cowboys",',
            'skin: s.theme === "titans" ? "titans" : "cowboys",',
            1,
        )
        html = html.replace(
            '<option value="cowboys">★ Cowboys mode</option>',
            '<option value="cowboys">★ Cowboys mode</option>'
            '<option value="titans">★ Titans mode</option>',
            1,
        )
        html = html.replace(
            'themeLabel: s.theme === "cowboys" ? "★ Cowboys mode"',
            'themeLabel: s.theme === "titans" ? "★ Titans mode" : '
            's.theme === "cowboys" ? "★ Cowboys mode"',
            1,
        )
        # The restore guard whitelists stored themes; let "titans" survive
        # a reload like the others do.
        html = html.replace(
            'if (th === "dark" || th === "light" || th === "cowboys")',
            'if (th === "dark" || th === "light" || th === "cowboys" || th === "titans")',
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
