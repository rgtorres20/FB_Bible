"""Vercel serverless entrypoint.

Vercel's Python runtime looks for a module-level ASGI app named `app`, so this
is just a re-export. Keeping it a separate file means the container/uvicorn
path (app.main:app) and the serverless path stay identical in behaviour.
"""

from app.main import app  # noqa: F401
