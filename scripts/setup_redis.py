"""One command to get Redis configured. Run it and paste when prompted.

    python scripts/setup_redis.py

Takes whatever Upstash gave you -- the full redis-cli command, a redis://
URL, a rediss:// URL, or just the bare password -- normalises it to the
rediss:// form the server needs, writes it into .env, and offers to push
everything to Vercel and redeploy.

The paste is hidden and goes straight into .env. It is never printed and
never leaves your machine except as a Vercel environment variable.
"""

from __future__ import annotations

import getpass
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"
DEFAULT_HOST = "viable-skink-136442.upstash.io"
DEFAULT_PORT = "6379"

URL_RE = re.compile(r"rediss?://(?P<user>[^:]+):(?P<password>[^@]+)@(?P<host>[^:/]+):(?P<port>\d+)")


def normalise(raw: str) -> str | None:
    """Accept any shape Upstash hands out; return a rediss:// URL."""
    raw = raw.strip().strip('"').strip("'")
    if not raw:
        return None

    match = URL_RE.search(raw)
    if match:
        # Force the TLS scheme: Upstash refuses plain connections, and its
        # redis-cli form carries TLS in a --tls flag the server never sees.
        return f"rediss://{match['user']}:{match['password']}@{match['host']}:{match['port']}"

    if raw.startswith("http"):
        return None  # the REST URL, which belongs to a different client

    # A bare password.
    if "@" not in raw and "/" not in raw and " " not in raw:
        return f"rediss://default:{raw}@{DEFAULT_HOST}:{DEFAULT_PORT}"

    return None


def write_env(url: str) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    out, replaced = [], False
    for line in lines:
        if line.startswith("REDIS_URL="):
            out.append(f"REDIS_URL={url}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"REDIS_URL={url}")
    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    print("Paste the Upstash connection string OR just the password, then Enter.")
    print("(Your typing stays hidden. Any format is fine -- it gets fixed up.)\n")

    try:
        raw = getpass.getpass("Upstash: ")
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 1

    url = normalise(raw)
    if not url:
        print("\nThat did not look like an Upstash connection string or password.")
        print("On the Upstash Details page, look for the value starting rediss://")
        print("or redis:// -- or just copy the password field on its own.")
        return 1

    write_env(url)
    host = URL_RE.search(url)
    print(f"\n  Wrote REDIS_URL to .env  ->  rediss://default:***@{host['host']}:{host['port']}")

    answer = input("\nPush all settings to Vercel and redeploy now? [Y/n] ").strip().lower()
    if answer and not answer.startswith("y"):
        print("Skipped. Run this when ready:")
        print("  python scripts/push_env_to_vercel.py")
        return 0

    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "push_env_to_vercel.py")],
        cwd=REPO_ROOT,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
