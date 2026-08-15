"""Vercel serverless entrypoint.

Vercel's Python runtime looks for a module-level ASGI app named `app`, so this
is mostly a re-export. Keeping it a separate file means the container/uvicorn
path (app.main:app) and the serverless path stay identical in behaviour.

The sys.path line is not ceremony: on Vercel this file is invoked from inside
the bundle, where the repository root is not necessarily on sys.path, and
`import app` then fails at invocation time as FUNCTION_INVOCATION_FAILED with
nothing useful in the response. Belt and braces alongside `includeFiles` in
vercel.json.

TEMPORARY (2026-08-14): the import is wrapped so that a failure serves the
traceback over HTTP instead of an opaque 500. Vercel's runtime logs are the
only other place that information exists, and they require dashboard access.
Remove the fallback once the deploy is healthy -- see docs/HOSTING.md.
"""

import json
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from app.main import app  # noqa: F401
except Exception:  # pragma: no cover - only runs on a broken deploy
    _DIAGNOSTIC = {
        "error": "import of app.main failed",
        "traceback": traceback.format_exc().splitlines(),
        "python_version": sys.version,
        "entrypoint_file": str(Path(__file__).resolve()),
        "repo_root": str(REPO_ROOT),
        "repo_root_exists": REPO_ROOT.is_dir(),
        # The decisive question: did includeFiles actually bundle the package?
        "repo_root_contents": sorted(p.name for p in REPO_ROOT.iterdir())
        if REPO_ROOT.is_dir()
        else None,
        "app_package_present": (REPO_ROOT / "app" / "__init__.py").is_file(),
        "sys_path": sys.path,
    }

    async def app(scope, receive, send):  # type: ignore[misc]
        """Minimal ASGI app — deliberately imports nothing, since the failure
        may well be a missing dependency."""
        if scope["type"] != "http":
            return
        body = json.dumps(_DIAGNOSTIC, indent=2).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 500,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
