"""FB Bible Phase 2 -- the Yahoo league link server.

Runs two ways from the same module, deliberately:
  * local / container:  uvicorn app.main:app --reload
  * Vercel serverless:  api/index.py imports `app`
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .feeds import board, vegas
from .feeds.store import FeedStore
from .routes import auth, feeds, league

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
    title="FB Bible -- Yahoo league link",
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
        "yahoo_configured": settings.configured,
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
            '<script src="mobile.js" defer></script></head>',
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
                        vegas.schedule_rows(state),
                        vegas.central_stamp(state.get("fetched_at")),
                    )
                # The Draft analyzer's ADP column, joined from the live
                # blend. Uncovered players show a dash rather than the
                # derived round.pick number they used to show.
                html, covered = board.inject(html, (stored.get("adp") or {}).get("state"))
                if covered:
                    logging.getLogger(__name__).info("board: %d rows carry live ADP", covered)
            except Exception as exc:  # noqa: BLE001 - overlays must never blank the page
                logging.getLogger(__name__).warning("live page overlays unavailable: %s", exc)
        # A beta deploy announces itself (styles in mobile.css). Prod and
        # local runs serve no badge at all.
        if settings.stage == "preview":
            html = html.replace("</body>", '<div id="fb-stage-badge">BETA</div></body>', 1)
        return HTMLResponse(html)

    app.mount("/app", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
