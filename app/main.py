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
from .feeds import vegas
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
        html = html.replace('gdMode: "build",', 'gdMode: "predict",', 1)
        html = html.replace(
            '[{ id: "build", label: "Build a team" }, { id: "predict", label: "Predictions" }]',
            '[{ id: "predict", label: "Predictions" }]',
            1,
        )
        # Live Vegas lines, same serve-time pattern. Every failure path keeps
        # the committed const: stale-but-honest beats a blank odds board.
        if store is not None:
            try:
                stored = await store.load()
                state = stored.get("vegas") or {}
                live = vegas.rows(state, vegas.curated_reads())
                html = vegas.inject(html, live, vegas.central_stamp(state.get("fetched_at")))
                # TD-lean confidence tracks the same live lines: leans stay
                # the owner's Aug-14 calls, confidence shifts with implied
                # totals, and the moved rows say so.
                if live:
                    adjusted = vegas.adjust_predictions(
                        vegas.curated_predictions(),
                        vegas.curated_implied(),
                        vegas.live_implied(live),
                    )
                    html = vegas.inject_predictions(html, adjusted)
            except Exception as exc:  # noqa: BLE001 - odds must never blank the page
                logging.getLogger(__name__).warning("vegas overlay unavailable: %s", exc)
        # A beta deploy announces itself (styles in mobile.css). Prod and
        # local runs serve no badge at all.
        if settings.stage == "preview":
            html = html.replace("</body>", '<div id="fb-stage-badge">BETA</div></body>', 1)
        return HTMLResponse(html)

    app.mount("/app", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
