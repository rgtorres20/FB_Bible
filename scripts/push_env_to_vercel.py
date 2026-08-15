"""Push the local .env into Vercel's production environment, then redeploy.

You run this, not Claude: it needs a Vercel session, and the values are
secrets. Nothing here prints a secret -- only names and lengths.

    npx vercel login       # once
    npx vercel link        # once, pick the fb-bible project
    python scripts/push_env_to_vercel.py

Add --dry-run to see exactly what it would do without touching Vercel.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"

# Everything the deployed function needs. YAHOO_* are optional for now: the
# server is designed to run without them and say so on /health.
REQUIRED = [
    "TOKEN_ENCRYPTION_KEY",
    "SESSION_SECRET",
    "REDIS_URL",
]

# Not read from .env: serverless has no writable disk, so Vercel always needs
# the redis store. Local dev keeps whatever .env says (the file store is
# simpler there), and the two no longer have to agree.
FORCED = {"TOKEN_STORE": "redis"}
OPTIONAL = [
    "SYNC_TOKEN",
    "YAHOO_CLIENT_ID",
    "YAHOO_CLIENT_SECRET",
    "YAHOO_REDIRECT_URI",
    "CORS_ORIGINS",
]


def read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        sys.exit(f"No {path.name} found at {path}. Copy .env.example and fill it in.")
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("\"'")
    return values


def vercel_cmd() -> list[str]:
    if shutil.which("vercel"):
        return ["vercel"]
    if shutil.which("npx"):
        return ["npx", "--yes", "vercel"]
    sys.exit("Neither `vercel` nor `npx` is on PATH. Install Node, then: npx vercel login")


def set_var(base: list[str], name: str, value: str, dry_run: bool) -> bool:
    """Replace one production variable. Returns True on success."""
    if dry_run:
        print(f"  would set {name}  ({len(value)} chars)")
        return True

    # Remove first: `env add` fails if the variable already exists.
    subprocess.run(
        [*base, "env", "rm", name, "production", "--yes"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    result = subprocess.run(
        [*base, "env", "add", name, "production"],
        input=value,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        # stderr can echo the value back, so report only the status.
        print(f"  FAILED {name} (exit {result.returncode})")
        return False
    print(f"  set {name}  ({len(value)} chars)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-deploy", action="store_true")
    args = parser.parse_args()

    env = read_env(ENV_FILE)

    missing = [k for k in REQUIRED if not env.get(k)]
    if missing:
        print("These are empty in .env and must be filled in first:")
        for key in missing:
            hint = {
                "REDIS_URL": "the rediss://... string from Upstash (NOT the REST URL/token)",
            }.get(key, "")
            print(f"  - {key}{'  <- ' + hint if hint else ''}")
        return 1

    if not env["REDIS_URL"].startswith(("rediss://", "redis://")):
        print("REDIS_URL does not look like a connection string.")
        print("Upstash also shows a REST URL and token -- those are for a different")
        print("client. You want the one starting rediss://")
        return 1

    base = vercel_cmd()
    print(f"Pushing to Vercel production via: {' '.join(base)}\n")

    ok = True
    for key in REQUIRED:
        ok &= set_var(base, key, env[key], args.dry_run)
    for key, value in FORCED.items():
        ok &= set_var(base, key, value, args.dry_run)
    for key in OPTIONAL:
        if env.get(key):
            ok &= set_var(base, key, env[key], args.dry_run)

    if not ok:
        print("\nSome variables failed. Are you logged in? Try: npx vercel login")
        return 1

    if args.dry_run:
        print("\nDry run only. Re-run without --dry-run to apply.")
        return 0

    if args.no_deploy:
        print("\nDone. Variables only apply to NEW deployments -- redeploy to pick them up.")
        return 0

    print("\nRedeploying (variables only apply to new deployments)...")
    result = subprocess.run([*base, "--prod"], cwd=REPO_ROOT)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
