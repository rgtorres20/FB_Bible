"""FB Bible Phase 2 -- the Yahoo league link server.

Runs two ways from the same module, deliberately:
  * local / container:  uvicorn app.main:app --reload
  * Vercel serverless:  api/index.py imports `app`
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .routes import auth, feeds, league

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
_FRONTEND_INDEX = _FRONTEND_DIR / "index.html"

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


@app.get("/health", tags=["meta"], summary="Liveness plus configuration state")
async def health() -> dict:
    """Deliberately reports config problems rather than just 'ok', so a bad
    deploy is visible without reading logs."""
    return {
        "status": "ok",
        "yahoo_configured": settings.configured,
        "token_store": settings.token_store,
        "encryption_configured": bool(settings.token_encryption_key),
        "league_keys": settings.league_keys,
        "frontend_deployed": _FRONTEND_INDEX.is_file(),
    }


# --- The app itself -------------------------------------------------------
# Serving the page from the same origin as the API is deliberate: it makes
# CORS a non-issue, puts the whole thing on one URL you can open on a phone,
# and means one deploy rather than two.
#
# Mounted last so /health, /api/* and /auth/* still win. Mounted at /app
# rather than / so it cannot shadow them by accident.
#
# frontend/index.html does not exist yet -- the page still lives in the Claude
# design project. Until it is committed, /app returns 404 and /health reports
# frontend_deployed: false. See docs/MIGRATION.md.
if _FRONTEND_DIR.is_dir():
    app.mount("/app", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
