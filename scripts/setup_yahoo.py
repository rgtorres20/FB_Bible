"""One command to finish the Yahoo link. Run it and paste when prompted.

    python scripts/setup_yahoo.py

Asks for the Client ID and Client Secret that Yahoo showed you after
creating the app, writes them into .env, pushes everything to Vercel,
redeploys, and prints the link to finish signing in.

You never edit a file. The secret is typed hidden and goes straight into
the gitignored .env; the only place it travels is Vercel's environment
variables.
"""

from __future__ import annotations

import getpass
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"
LOGIN_URL = "https://fb-bible-torro2.vercel.app/auth/yahoo/login"

# Yahoo's console labels these inconsistently, and people paste the label too.
LABELS = re.compile(
    r"^\s*(client\s*id|client\s*secret|consumer\s*key|consumer\s*secret|app\s*id)\s*[:=]?\s*",
    re.I,
)


def clean(raw: str) -> str:
    """Strip a pasted label, quotes and stray whitespace."""
    return LABELS.sub("", raw.strip()).strip().strip('"').strip("'").strip()


def set_env(updates: dict[str, str]) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    seen = set()
    out = []
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line else None
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    print("From the Yahoo app page. Paste each value, then Enter.\n")

    try:
        client_id = clean(input("Client ID     : "))
        client_secret = clean(getpass.getpass("Client Secret : (hidden) "))
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 1

    if not client_id or not client_secret:
        print("\nBoth values are required. Nothing was changed.")
        return 1

    # Yahoo IDs are long; a short paste usually means a label or partial copy.
    if len(client_id) < 20 or len(client_secret) < 20:
        print(f"\nThose look too short (id {len(client_id)}, secret {len(client_secret)} chars).")
        print("Yahoo's values are 30+ characters. Nothing was changed -- try again.")
        return 1

    set_env({"YAHOO_CLIENT_ID": client_id, "YAHOO_CLIENT_SECRET": client_secret})
    print(f"\n  Wrote both to .env (id {len(client_id)} chars, secret {len(client_secret)} chars)")

    answer = input("\nPush to Vercel and redeploy now? [Y/n] ").strip().lower()
    if answer and not answer.startswith("y"):
        print("Skipped. Run this when ready:")
        print("  python scripts/push_env_to_vercel.py")
        return 0

    code = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "push_env_to_vercel.py")],
        cwd=REPO_ROOT,
    ).returncode

    if code == 0:
        print("\nDone. Finish signing in here:")
        print(f"  {LOGIN_URL}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
