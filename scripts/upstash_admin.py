"""Read the Upstash database's plan and usage, or turn on Auto Upgrade.

Oct 23: the plan's bandwidth cap was hit and Upstash refused every request,
so the whole app answered 500. Fixing it means a plan change in the owner's
Upstash account. This script does that through Upstash's official Developer
API (https://api.upstash.com/v2, HTTP basic auth: account email + management
API key) instead of anyone signing in to the console.

Run only by the manual `upstash.yml` workflow, which passes the two GitHub
secrets as env vars. Never prints the key, the password, or a connection URL
-- only names, plan fields and numbers.

  status       list databases: plan, auto-upgrade, region, and usage stats
  autoupgrade  enable Auto Upgrade on the database named in UPSTASH_DB
               (or the only database, if there is just one). This can raise
               the bill: the plan moves up a tier when a limit is hit.
"""

from __future__ import annotations

import os
import sys

import httpx

API = "https://api.upstash.com/v2"
# Fields worth showing. Anything credential-shaped is never printed.
SAFE = (
    "database_name", "database_id", "database_type", "type", "region",
    "primary_region", "state", "auto_upgrade", "budget", "creation_time",
    "db_max_clients", "db_max_request_size", "db_disk_threshold",
    "db_max_entry_size", "db_memory_threshold", "db_max_commands_per_second",
)  # fmt: skip
SECRETISH = ("password", "token", "secret", "endpoint", "url", "key")


def client() -> httpx.Client:
    email = os.environ.get("UPSTASH_EMAIL", "")
    key = os.environ.get("UPSTASH_API_KEY", "")
    if not email or not key:
        sys.exit("UPSTASH_EMAIL and UPSTASH_API_KEY secrets are required")
    return httpx.Client(base_url=API, auth=(email, key), timeout=30)


def show_stats(stats: dict) -> None:
    """Upstash's stats payload, numbers only: scalars printed, series
    summarised as their latest and total."""
    for name, value in sorted(stats.items()):
        if any(s in name.lower() for s in SECRETISH):
            continue
        if isinstance(value, int | float | str | bool):
            print(f"    {name}: {value}")
        elif isinstance(value, list) and value and isinstance(value[-1], dict):
            ys = [p.get("y") for p in value if isinstance(p.get("y"), int | float)]
            if ys:
                print(f"    {name}: latest {ys[-1]:,} · sum {sum(ys):,} over {len(ys)} points")


def status(http: httpx.Client) -> list[dict]:
    r = http.get("/redis/databases")
    print(f"databases: HTTP {r.status_code}")
    r.raise_for_status()
    dbs = r.json()
    for db in dbs:
        print(f"\n== {db.get('database_name')} ==")
        for field in SAFE:
            if field in db:
                print(f"  {field}: {db[field]}")
        s = http.get(f"/redis/stats/{db['database_id']}")
        print(f"  stats: HTTP {s.status_code}")
        if s.status_code == 200:
            show_stats(s.json())
    return dbs


def autoupgrade(http: httpx.Client) -> None:
    dbs = status(http)
    wanted = os.environ.get("UPSTASH_DB", "")
    pick = [d for d in dbs if not wanted or d.get("database_name") == wanted]
    if len(pick) != 1:
        sys.exit(f"name the database in UPSTASH_DB: {[d.get('database_name') for d in dbs]}")
    db = pick[0]
    r = http.post(f"/redis/enable-autoupgrade/{db['database_id']}")
    print(f"\nenable-autoupgrade {db.get('database_name')}: HTTP {r.status_code} {r.text[:200]}")
    r.raise_for_status()
    after = http.get(f"/redis/database/{db['database_id']}").json()
    print(
        f"auto_upgrade now: {after.get('auto_upgrade')} · "
        f"type {after.get('type') or after.get('database_type')}"
    )


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    with client() as http:
        (autoupgrade if action == "autoupgrade" else status)(http)
