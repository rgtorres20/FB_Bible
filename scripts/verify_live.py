"""Live-production verification: everything fixed must stay fixed.

CI proves the code; this proves the deployment. It runs on a schedule from
GitHub Actions and asserts against the real site, so a regression emails the
owner instead of waiting to be noticed in the app -- the failure mode this
project exists to kill is exactly "looked fine, was stale".

stdlib only: the job should never fail because of its own dependencies.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import UTC, datetime, timedelta

# Overridable so the same 35 checks can be pointed at a preview deployment.
# `or` rather than a get() default: an unset workflow input arrives as an
# empty string, which must not silently blank the URL.
BASE = os.environ.get("FBBIBLE_BASE") or "https://fb-bible-torro2.vercel.app"

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
    # Reported, not asserted -- the same run has to serve both stages. What
    # matters is that a preview says "preview": that is what raises the BETA
    # badge, and a preprod indistinguishable from prod is how you edit the
    # wrong one during a draft.
    stage = health.get("stage", "?")
    print(f"  INFO  stage: {stage}  branch: {health.get('branch') or '(none reported)'}")
    if stage == "preview":
        served_early = get("/app/").decode("utf-8", errors="replace")
        check("preview wears the BETA badge", 'id="fb-stage-badge"' in served_early)

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

    # Reported, not asserted. Verdicts are best-effort: the job exits 0 on a
    # rate limit or a missing key, so a zero hour is legitimate and failing
    # here would cry wolf. But a permanent break used to be invisible -- and
    # a sync bug silently deleted every verdict for a day before anyone
    # noticed -- so the count belongs in the log either way.
    drafted = sum(1 for e in page_data.get("news", []) if str(e.get("impact", "")).startswith("AI"))
    print(f"  INFO  AI-drafted verdicts on the news tab: {drafted}")

    # --- live draft-prep surfaces (Aug 15) ---------------------------------
    scout = page_data.get("scout", [])
    check(
        "Scout finds are live-generated",
        bool(scout)
        and any("FFC" in e.get("src", "") or "Sleeper rank" in e.get("src", "") for e in scout),
        f"{len(scout)} cards",
    )
    vegas_rows = page_data.get("vegas", [])
    check("Vegas slate present", len(vegas_rows) >= 8, f"{len(vegas_rows)} games")
    check(
        "Vegas slate marked live in Data health",
        "live" in meta.get("Vegas lines", {}).get("source", ""),
    )
    cheat = get("/app/cheatsheet").decode("utf-8", errors="replace")
    check("cheat sheet serves the live board", "rushing league" in cheat and "Blend" in cheat)

    # The top-300 alert board: one row per ranked player, wire-checked, with
    # machine lines labelled by author. Population needs the player index,
    # which the hourly sync keeps warm -- fewer than 250 rows means the
    # surface has degraded to its honest empty state.
    top300 = get("/app/alerts300").decode("utf-8", errors="replace")
    check("top-300 alert board serves", "Top-300 alert board" in top300)
    check(
        "top-300 board is populated",
        top300.count("<tr>") >= 250,
        f"{top300.count('<tr>')} rows",
    )
    check("top-300 board credits Sleeper", "data: Sleeper" in top300)
    drafted300 = top300.count("AI draft:")
    print(f"  INFO  AI-drafted lines on the top-300 board: {drafted300}")
    # Same best-effort rule as verdicts: the capsule and mover-read jobs
    # exit 0 on a rate limit or missing key, so zero is a legitimate hour --
    # but a silent wipe or a permanently dead job shows up as a count stuck
    # at zero, which is why the numbers belong in the log.
    angles = top300.count("AI angle:")
    print(f"  INFO  AI player capsules on the top-300 board: {angles}")
    reads = sum(1 for e in scout if "AI read:" in str(e.get("text", "")))
    print(f"  INFO  AI reads on the ADP mover cards: {reads}")

    # --- the served page carries tonight's fixes --------------------------
    served = get("/app/").decode("utf-8", errors="replace")
    check("mobile stylesheet injected", 'href="mobile.css"' in served)
    check("menu script injected", 'src="mobile.js"' in served)
    check("FFBets lands on Predictions", 'gdMode: "predict",' in served)
    # Strict on purpose: once the live board has shipped, a revert to the
    # curated openers means the odds pipeline is stale -- a true failure.
    check("vegas table rebound to live data", "vegas: (F.vegas || VEGAS)," in served)
    check("Vegas lines are live", "Live via ESPN" in served)
    check("TD leans track live lines", "confidence adjusted" in served)
    check("Week 1 schedule is live", "live kickoff times" in served)
    # The draft board's ADP column: real numbers, and no consumer left
    # reading the old derived round.pick string.
    check("draft board carries live ADP", "const FB_LIVE_ADP = " in served)
    check("no consumer reads the derived ADP", "parseFloat(b.adp)" not in served)
    # Team-intel usage reads: measured '25 pass rate and red-zone run share
    # replace the curated estimates, and the label names the stat -- a
    # revert to "GL x% run" over estimates is the stale-data failure mode.
    check("Team intel usage reads are live", "FB live usage: Sleeper '25 season" in served)
    check("red-zone run share is labelled", "% run share ('25)" in served)
    # A player listed twice appears twice mid-draft, and marking one row
    # taken leaves the other looking available.
    rows = re.search(r"const RAW_BOARD = \[(.*?)\n\];", served, re.S)
    board_names = re.findall(r'^\s*\[\d+,"([^"]+)"', rows.group(1), re.M) if rows else []
    check(
        "board has no duplicate players",
        bool(board_names) and len(board_names) == len(set(board_names)),
        f"{len(board_names)} rows, {len(set(board_names))} distinct",
    )
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
