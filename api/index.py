"""Vercel serverless entrypoint.

Vercel's Python runtime looks for a module-level ASGI app named `app`, so this
is mostly a re-export. Keeping it a separate file means the container/uvicorn
path (app.main:app) and the serverless path stay identical in behaviour.

The sys.path line is not ceremony: on Vercel this file is invoked from inside
the bundle, where the repository root is not necessarily on sys.path, and
`import app` then fails at invocation time as FUNCTION_INVOCATION_FAILED with
nothing useful in the response. Belt and braces alongside `includeFiles` in
vercel.json.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.main import app  # noqa: E402,F401
