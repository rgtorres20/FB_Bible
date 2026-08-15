"""TEMPORARY diagnostic entrypoint. Delete once the deploy is healthy.

Vercel returns FUNCTION_INVOCATION_FAILED with no detail, and the traceback
only exists in dashboard logs. This module is pure stdlib -- it cannot itself
fail to import -- and reports exactly which import in the chain breaks.

Point at it with `[tool.vercel] entrypoint = "probe:app"`, deploy, read the
JSON, then revert to `app.main:app`.
"""

import json
import os
import platform
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _try(label: str, fn):
    try:
        return {"ok": True, "label": label, "detail": fn()}
    except Exception:
        return {
            "ok": False,
            "label": label,
            "detail": traceback.format_exc().strip().splitlines()[-6:],
        }


def _collect() -> dict:
    checks = [
        _try("import fastapi", lambda: __import__("fastapi").__version__),
        _try("import pydantic", lambda: __import__("pydantic").VERSION),
        _try("import pydantic_settings", lambda: "ok"),
        _try("import httpx", lambda: __import__("httpx").__version__),
        _try("import cryptography", lambda: __import__("cryptography").__version__),
        _try("import redis", lambda: __import__("redis").__version__),
        _try("import app", lambda: str(__import__("app").__file__)),
        _try("import app.config", lambda: "ok"),
        _try("import app.store", lambda: "ok"),
        _try("import app.yahoo", lambda: "ok"),
        _try("import app.routes", lambda: "ok"),
        _try("import app.main", lambda: "ok"),
    ]
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "cwd": os.getcwd(),
        "probe_file": str(Path(__file__).resolve()),
        "root_contents": sorted(p.name for p in ROOT.iterdir()),
        "app_pkg_present": (ROOT / "app" / "__init__.py").is_file(),
        "sys_path": sys.path,
        "first_failure": next((c["label"] for c in checks if not c["ok"]), None),
        "checks": checks,
    }


async def app(scope, receive, send):
    if scope["type"] != "http":
        return
    try:
        body = json.dumps(_collect(), indent=2, default=str).encode()
    except Exception:
        body = traceback.format_exc().encode()
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
