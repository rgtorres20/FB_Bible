"""Live-production verification: everything fixed must stay fixed.

CI proves the code; this proves the deployment. It runs on a schedule from
GitHub Actions and asserts against the real site, so a regression emails the
owner instead of waiting to be noticed in the app -- the failure mode this
project exists to kill is exactly "looked fine, was stale".

stdlib only: the job should never fail because of its own dependencies.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import UTC, datetime, timedelta

BASE = "https://fb-bible-torro2.vercel.app"

# The cron is configured every 15 minutes but GitHub delivers roughly hourly
# on free public repos; three hours means "genuinely broken", not "jittery".
MAX_FEED_AGE = timedelta(hours=3)

failures: list[str] = []
passes: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    (passes if ok else failures).append(f"{label}{': ' + detail if detail else ''}")
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{': ' + detail if detail else ''}")


def get(path: str) -> bytes:
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "FBBible-verify/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def get_json(path: str) -> dict:
    return json.loads(get(path))


def main() -> int:
    print(f"verifying {BASE} at {datetime.now(UTC).isoformat()}\n")

    # --- server configuration ---------------------------------------------
    health = get_json("/health")
    check("health.status", health.get("status") == "ok")
    check("health.token_store is redis", health.get("token_store") == "redis")
    check("health.encryption configured", health.get("encryption_configured") is True)
    check("health.frontend ready", health.get("frontend_ready") is True)

    # --- the news pipeline actually updates -------------------------------
    feeds = get_json("/api/feeds?limit=1")
    check("feed has items", feeds.get("total", 0) > 50, f"total={feeds.get('total')}")

    polled = feeds.get("polled_at")
    age = None
    if polled:
        age = datetime.now(UTC) - datetime.fromisoformat(polled)
    check(
        "feed polled recently",
        age is not None and age < MAX_FEED_AGE,
        f"age={age}" if age else "no polled_at",
    )

    sources = feeds.get("sources", {})
    check("all sources present", len(sources) >= 6, f"got {len(sources)}")
    for key, status in sorted(sources.items()):
        check(f"source {key} not FAILED", status.get("state") != "FAILED", status.get("state", "?"))

    # --- what the page actually receives ----------------------------------
    page_data = get_json("/app/data/feeds.json")
    check("page news is the live overlay", len(page_data.get("news", [])) > 25)
    check(
        "NBC tab carries live rows",
        any(
            str(entry.get("lean", "")).startswith("Auto:") or entry.get("link")
            for entry in page_data.get("rotowire", [])
        ),
    )
    meta = {m.get("feed"): m for m in page_data.get("meta", [])}
    news_as_of = meta.get("News & posts", {}).get("asOf", "")
    # asOf is naive Central ("2026-08-15T02:27"); yesterday's date means the
    # overlay stopped stamping. Central is UTC-5/6, so compare against a
    # generously-lagged UTC date rather than converting.
    lagged = f"{datetime.now(UTC) - timedelta(hours=30):%Y-%m-%d}"
    check("Data health stamp updates", news_as_of[:10] >= lagged, news_as_of)

    # --- the served page carries tonight's fixes --------------------------
    served = get("/app/").decode("utf-8", errors="replace")
    check("mobile stylesheet injected", 'href="mobile.css"' in served)
    check("menu script injected", 'src="mobile.js"' in served)
    check("FFBets lands on Predictions", 'gdMode: "predict",' in served)
    # Strict on purpose: once the live board has shipped, a revert to the
    # curated openers means the odds pipeline is stale -- a true failure.
    check("Vegas lines are live", "Live via ESPN" in served)
    check("TD leans track live lines", "confidence adjusted" in served)
    check("Week 1 schedule is live", "live kickoff times" in served)
    check("Build-a-team shelved", '{ id: "build", label: "Build a team" }' not in served)

    mobile_css = get("/app/mobile.css")
    check("mobile.css serves", b"min-height: 100vh" in mobile_css)
    check("wire-stamp styles serve", b"fb-wire-stamp" in mobile_css)
    mobile_js = get("/app/mobile.js")
    check("mobile.js serves", b"fb-menu-btn" in mobile_js)
    check("overlay decorator serves", b"fb-new-badge" in mobile_js and b"injury_wire" in mobile_js)

    # --- verdict -----------------------------------------------------------
    print(f"\n{len(passes)} passed, {len(failures)} failed")
    if failures:
        print("\nFAILED checks:")
        for f in failures:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - a crashed check run must still fail loudly
        print(f"\nverification crashed: {type(exc).__name__}: {exc}")
        raise SystemExit(2) from exc
