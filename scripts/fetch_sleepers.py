"""Community sleeper consensus: who the fantasy wire is actually recommending.

The Sleepers tab's editable watchlist answered "whose believer am I?" —
this answers the other question the owner asked for on Aug 25: a thread
that *searches the wire* for sleeper talk. It reads full articles from
fantasy publishers, asks the AI reader what each author is really saying
about each player named (recommending? warning off? merely mentioning?),
and blends the positive calls across sources with Sleeper's add/drop
trends into one ranked consensus list, pushed to the deployment.

Handed off from a chat-thread draft (Aug 28) and adapted to this repo:

- **The provider is the repo's, not Anthropic's.** The draft called the
  Anthropic API with a hardcoded model name; the owner picked Google AI
  Studio on cost (Aug 15, docs/AI.md) and every model call in the repo
  goes through `draft_verdicts.chat_with_retry` — same key, same
  fallback ladder, same permanent-vs-transient discipline. One config,
  not two.
- **The matcher is the app's, not a second one.** The draft shipped its
  own name normalizer and player map; `app.feeds.players` already
  fetches the Sleeper dump and matches names precision-first (unique
  surnames only, common-word surnames refused). Two matchers is how one
  of them stays wrong.
- **Output is pushed, never committed.** The draft's workflow committed
  feeds.json from a bot; this repo's pattern is POST /internal/* with
  X-Sync-Token — the runner provides the network vantage point, the
  deployment stores and serves (same split as the Vegas slate).

Stores links and the model's own one-line paraphrases. Never stores
source article text.

Env:
    AI_API_KEY / GEMINI_API_KEY   the model key (as draft_verdicts)
    SYNC_TOKEN                    required to push
    FBBIBLE_BASE                  deployment base URL
    SEASON                        defaults to the current year

Modes:
    --check-feeds   probe every source and both Sleeper endpoints,
                    print OK/DEAD, spend no model credits. Run this
                    from the Actions runner (the dev session usually
                    cannot reach these hosts) before trusting SOURCES.
    --dry-run       full pipeline, print the payload instead of pushing.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.feeds import players  # noqa: E402
from scripts.draft_verdicts import (  # noqa: E402
    BASE,
    PERMANENT_CODES,
    chat_with_retry,
    http_json,
)

SEASON = os.environ.get("SEASON", str(datetime.now(UTC).year))
LOOKBACK_DAYS = 10
MAX_ARTICLES = 40
MAX_CANDIDATES = 15
# Politeness between publisher fetches; the model calls pace themselves
# further below (AI_CALL_DELAY) because the free tier's per-minute window
# is the real constraint, measured on the verdicts job (runs 50-52).
REQUEST_DELAY = 1.5
AI_CALL_DELAY = 6.0
UA = "FBBible/0.1 (personal fantasy tool)"

# name, feed url, kind. The seven active ones were chosen in the handoff
# thread; NONE were reachable from the dev sandbox, so the check-feeds
# mode of the sleepers workflow is the verifier — prune what it calls
# DEAD there, not from guesswork here.
SOURCES = [
    ("PFF", "https://www.pff.com/feed", "rss"),
    ("PlayerProfiler", "https://www.playerprofiler.com/feed", "rss"),
    ("Razzball", "https://football.razzball.com/feed", "rss"),
    ("DynastyLeagueFootball", "https://dynastyleaguefootball.com/feed", "rss"),
    ("ESPN NFL", "https://www.espn.com/espn/rss/nfl/news", "rss"),
    # FantasySP's feeds are free for NON-COMMERCIAL use only — fine for a
    # personal tool, but docs/LICENSING.md lists it among the things that
    # must be dropped or licensed before Fantasy Bible is ever sold.
    ("FantasySP", "https://www.fantasysp.com/rss/nfl/headlines/", "rss"),
    (
        "r/fantasyfootball",
        "https://www.reddit.com/r/fantasyfootball/search.json"
        "?q=sleeper+OR+breakout&sort=new&restrict_sr=1&t=week&limit=40",
        "reddit",
    ),
    # --- UNVERIFIED, disabled by default ---
    # FantasyPros publishes no RSS URL anywhere findable — they push their
    # paid API (fantasypros.com/api-data/). These are WordPress-shape
    # guesses. Uncomment, run check-feeds from the workflow, keep what
    # answers.
    # ("FantasyPros Sleepers", "https://www.fantasypros.com/content/sleepers-nfl/feed/", "rss"),
    # ("FantasyPros Articles", "https://www.fantasypros.com/nfl/articles/feed/", "rss"),
    # ("RotoBaller", "https://www.rotoballer.com/category/nfl/feed", "rss"),
]

# Offensive skill positions, plus every defender the owner's IDP leagues
# can start (players.idp_group). Team defenses (dst) are excluded: a city
# name in a headline is a story about a team, not a sleeper.
OFFENSE = frozenset({"QB", "RB", "WR", "TE"})

SYSTEM_PROMPT = """You analyze fantasy football articles and extract the author's \
stance on specific players.

You will receive an article and a list of candidate players that were detected in \
its text. For each candidate, decide what the author is actually saying about them.

Return ONLY a JSON array. No preamble, no markdown fences, no explanation.

Each element:
{
  "player_id": "<the id given to you>",
  "verdict": "sleeper" | "breakout" | "bust" | "fade" | "mentioned",
  "reason": "<your own one-sentence summary, max 25 words, in your own words>",
  "confidence": 0.0-1.0
}

Rules:
- "sleeper"/"breakout" only when the author is recommending drafting or targeting.
- "bust"/"fade" when the author is warning off or avoiding.
- "mentioned" for players named only as context (a teammate, a comparison, a \
competitor for touches). Most candidates are this. Do not inflate.
- reason must be YOUR paraphrase, never a quote or near-quote from the article.
- Omit no candidate. If unsure, use "mentioned" with low confidence."""

POSITIVE = frozenset({"sleeper", "breakout"})
NEGATIVE = frozenset({"bust", "fade"})
# Below this the model itself is unsure the stance is real; chosen, not
# measured — docs/ASSUMPTIONS.md.
MIN_CONFIDENCE = 0.4


def _get(url: str, timeout: float = 25.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _get_json(url: str) -> dict | list:
    return json.loads(_get(url))


# ------------------------------------------------------- sleeper platform


def fetch_trending(kind: str = "add", hours: int = 72, limit: int = 100) -> dict[str, int]:
    url = (
        f"https://api.sleeper.app/v1/players/nfl/trending/{kind}"
        f"?lookback_hours={hours}&limit={limit}"
    )
    try:
        rows = _get_json(url)
        return {str(row["player_id"]): int(row["count"]) for row in rows}
    except Exception as exc:  # noqa: BLE001 - trending is a weight, not a gate
        print(f"  trending/{kind} failed: {type(exc).__name__}: {exc}")
        return {}


def fetch_ownership() -> dict[str, float]:
    """Roster percentages, or {} when the endpoint has nothing.

    Season type depends on where the calendar is and Sleeper does not
    announce the flip, so try the most useful first and fall back. Week is
    optional — omitting it gives season-wide numbers. Fails soft: scoring
    degrades gracefully to consensus + trending only.
    """
    attempts = [
        ("regular", "1"),  # once Week 1 is live, the real number
        ("pre", "1"),  # preseason draft window
        ("off", None),  # deep offseason
    ]
    for season_type, week in attempts:
        url = f"https://api.sleeper.com/players/nfl/research/{season_type}/{SEASON}"
        if week:
            url += f"/{week}"
        try:
            data = _get_json(url)
            if not data:
                print(f"  ownership: {season_type} empty, trying next")
                continue
            print(f"  ownership: using '{season_type}' ({len(data)} players)")
            return {str(pid): float(v.get("owned", 0) or 0) for pid, v in data.items()}
        except Exception as exc:  # noqa: BLE001 - same soft failure as above
            print(f"  ownership: {season_type} failed ({type(exc).__name__}: {exc})")
    print("  ownership unavailable — scoring without roster%")
    return {}


# ------------------------------------------------------------- ingestion


def _parse_feed(url: str):
    """feedparser, imported where it is used: the module has to import
    clean in environments that only run the pure parts (tests, --help)."""
    import feedparser

    return feedparser.parse(url, agent=UA)


def _reddit_items(name: str, url: str, cutoff: datetime) -> list[dict]:
    items = []
    payload = _get_json(url)
    for child in payload["data"]["children"]:
        d = child["data"]
        pub = datetime.fromtimestamp(d["created_utc"], UTC)
        # Low-score threads are one person's guess; 25 net upvotes is the
        # handoff's line for "the room agrees this is worth reading".
        if pub < cutoff or d.get("score", 0) < 25:
            continue
        items.append(
            {
                "source": name,
                "title": d["title"],
                "url": "https://www.reddit.com" + d["permalink"],
                "published": pub.isoformat(),
                # Self-posts carry their text in the listing; no second fetch.
                "inline_text": (d.get("selftext") or "")[:6000],
            }
        )
    return items


def _rss_items(name: str, url: str, cutoff: datetime) -> list[dict]:
    items = []
    parsed = _parse_feed(url)
    for entry in parsed.entries:
        pub = None
        if getattr(entry, "published_parsed", None):
            pub = datetime(*entry.published_parsed[:6], tzinfo=UTC)
        if pub and pub < cutoff:
            continue
        items.append(
            {
                "source": name,
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "published": (pub or datetime.now(UTC)).isoformat(),
                "inline_text": "",
            }
        )
    return items


def collect_items() -> list[dict]:
    """[{source, title, url, published, inline_text}] in the window, newest
    first, capped. A failed source is reported and skipped — four of seven
    publishers is still a consensus."""
    cutoff = datetime.now(UTC) - timedelta(days=LOOKBACK_DAYS)
    items: list[dict] = []
    for name, url, kind in SOURCES:
        try:
            if kind == "reddit":
                items.extend(_reddit_items(name, url, cutoff))
            else:
                items.extend(_rss_items(name, url, cutoff))
            print(f"  {name}: ok")
        except Exception as exc:  # noqa: BLE001 - one dead publisher must not kill the run
            print(f"  {name}: FAILED ({type(exc).__name__}: {exc})")
        time.sleep(REQUEST_DELAY)

    items.sort(key=lambda i: i["published"], reverse=True)
    return items[:MAX_ARTICLES]


def article_text(item: dict) -> str:
    if item.get("inline_text"):
        return item["inline_text"]
    try:
        import trafilatura

        downloaded = trafilatura.fetch_url(item["url"])
        if not downloaded:
            return ""
        return (trafilatura.extract(downloaded) or "")[:12000]
    except Exception as exc:  # noqa: BLE001 - an unextractable page is a skipped page
        print(f"    extract failed: {type(exc).__name__}: {exc}")
        return ""


# -------------------------------------------------------------- matching


def candidates_in(text: str, index: dict) -> list[dict]:
    """Players the article names, through the app's own matcher.

    Defenders stay in — both verified leagues start eight of them
    (docs/LEAGUES.md) and a sleeper list that ignores a third of the
    roster is the mistake /app/nextup already had to fix. Team defenses
    are dropped: a city name is a story about a team, not a draftable
    sleeper. Kickers and linemen fall out with them.
    """
    found = players.find_players(text, index, limit=MAX_CANDIDATES * 2)
    kept = [p for p in found if not p.get("dst") and (p.get("position") in OFFENSE or p.get("idp"))]
    return kept[:MAX_CANDIDATES]


# --------------------------------------------------------- classification


def _strip_fence(content: str) -> str:
    """Models love to wrap JSON in a code fence; strip it rather than fail."""
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        content = content.split("\n", 1)[1] if "\n" in content else content
        content = content.rsplit("```", 1)[0] if "```" in content else content
    return content.strip()


def classify(text: str, candidates: list[dict], api_key: str) -> list[dict]:
    """One model call: the article and its candidates in, stances out.

    Raises urllib.error.HTTPError on a permanent rejection (bad key, dead
    model) so the caller can stop the batch — retrying a retired model 40
    times is just a slower way to be wrong. Anything else malformed
    returns [] and costs only this article.
    """
    if not candidates:
        return []
    roster = "\n".join(
        f"- {c['id']}: {c['name']} ({c.get('position')} - {c.get('team') or 'FA'})"
        for c in candidates
    )
    response = chat_with_retry(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"CANDIDATE PLAYERS:\n{roster}\n\nARTICLE:\n{text}"},
        ],
        api_key,
    )
    try:
        content = response["choices"][0]["message"]["content"]
        rows = json.loads(_strip_fence(content))
        return rows if isinstance(rows, list) else []
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        print(f"    reply unusable, skipping article: {type(exc).__name__}: {exc}")
        return []


# ------------------------------------------------------------ aggregation


def keep_stance(row: dict) -> bool:
    """A row worth counting: a real stance the model itself believes."""
    verdict = row.get("verdict")
    if verdict not in POSITIVE and verdict not in NEGATIVE:
        return False
    try:
        return float(row.get("confidence", 0)) >= MIN_CONFIDENCE
    except (TypeError, ValueError):
        return False


def rank_consensus(
    mentions_by_player: dict[str, list[dict]],
    meta: dict[str, dict],
    trending_add: dict[str, int],
    trending_drop: dict[str, int],
    owned: dict[str, float],
    now: datetime | None = None,
) -> list[dict]:
    """Blend cross-source stances with Sleeper trends into a ranked list.

    The shape of the score (docs/ASSUMPTIONS.md): sources × recency say
    how broad and how current the recommendation is, add/drop buzz leans
    on it, and roster% divides it — a player everyone already holds is
    not a sleeper whatever the wire says. Dissent (bust/fade calls) is
    reported beside the score rather than subtracted from it: "three
    sites love him, one is out" is a finding the reader should see, not
    an average that hides both.
    """
    now = now or datetime.now(UTC)
    results = []
    for pid, mentions in mentions_by_player.items():
        pos_hits = [m for m in mentions if m["verdict"] in POSITIVE]
        neg_hits = [m for m in mentions if m["verdict"] in NEGATIVE]
        if not pos_hits or pid not in meta:
            continue

        # Recency: a call made in the last 3 days counts double.
        recency = 0.0
        for m in pos_hits:
            age = (now - datetime.fromisoformat(m["published"])).days
            recency += 2.0 if age <= 3 else 1.0

        sources = sorted({m["source"] for m in pos_hits})
        adds = trending_add.get(pid, 0)
        drops = trending_drop.get(pid, 0)
        roster_pct = owned.get(pid, 0) or 0

        buzz = (adds - drops * 0.5) / 1000.0
        score = (len(sources) * recency * (1 + buzz)) / (1 + roster_pct / 20.0)

        p = meta[pid]
        results.append(
            {
                "player_id": pid,
                "name": p["name"],
                "position": p.get("idp") or p.get("position") or "",
                "team": p.get("team") or "",
                "injury_status": p.get("injury_status") or "",
                "score": round(score, 2),
                "source_count": len(sources),
                "mention_count": len(pos_hits),
                "dissent_count": len(neg_hits),
                "trending_adds_72h": adds,
                "roster_pct": round(roster_pct, 1),
                "reasons": [m["reason"] for m in pos_hits[:3]],
                "links": [
                    {
                        "source": m["source"],
                        "title": m["title"],
                        "url": m["url"],
                        "published": m["published"],
                    }
                    for m in sorted(pos_hits, key=lambda x: x["published"], reverse=True)[:5]
                ],
            }
        )

    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def build_consensus(items: list[dict], index: dict, api_key: str) -> tuple[list[dict], int]:
    """Read every article, collect stances, rank. Returns (rows, articles_read)."""
    mentions: dict[str, list[dict]] = defaultdict(list)
    meta: dict[str, dict] = {}
    read = 0

    for i, item in enumerate(items, 1):
        print(f"[{i}/{len(items)}] {item['title'][:70]}")
        text = article_text(item)
        if len(text) < 400:
            continue
        candidates = candidates_in(text, index)
        if not candidates:
            continue
        print(f"    {len(candidates)} candidates -> classifying")
        try:
            rows = classify(text, candidates, api_key)
        except urllib.error.HTTPError as exc:
            if exc.code in PERMANENT_CODES:
                # A dead model fails the same way 40 times; stop paying for
                # the lesson and keep whatever the run has already earned.
                print(f"::error::model rejected permanently (HTTP {exc.code}); stopping batch")
                break
            print(f"    model call failed (HTTP {exc.code}), skipping article")
            continue
        read += 1
        by_id = {c["id"]: c for c in candidates}
        for row in rows:
            pid = str(row.get("player_id", ""))
            if pid not in by_id or not keep_stance(row):
                continue
            meta[pid] = by_id[pid]
            mentions[pid].append(
                {
                    "source": item["source"],
                    "title": item["title"],
                    "url": item["url"],
                    "published": item["published"],
                    "verdict": row["verdict"],
                    "reason": str(row.get("reason", ""))[:200],
                }
            )
        time.sleep(AI_CALL_DELAY)

    trending_add = fetch_trending("add")
    trending_drop = fetch_trending("drop")
    owned = fetch_ownership()
    return rank_consensus(mentions, meta, trending_add, trending_drop, owned), read


# ----------------------------------------------------------------- output


def push_state(rows: list[dict], articles_read: int, sync_token: str) -> None:
    state = {
        "season": SEASON,
        "article_count": articles_read,
        "sources_surveyed": [name for name, _, _ in SOURCES],
        "players": rows[:40],
    }
    result = http_json(
        f"{BASE}/internal/sleepers",
        payload={"state": state},
        headers={"X-Sync-Token": sync_token},
    )
    print(f"posted: {result}")


def check_feeds() -> None:
    """Probe every source without burning model credits. Run this first —
    from the sleepers workflow's check mode, because the dev session's
    network usually cannot reach these hosts at all."""
    print("checking sources...\n")
    good, bad = [], []
    for name, url, kind in SOURCES:
        try:
            if kind == "reddit":
                n = len(_get_json(url)["data"]["children"])
            else:
                n = len(_parse_feed(url).entries)
                if n == 0:
                    raise ValueError("0 entries (dead URL or blocked)")
            print(f"  OK    {name:<26} {n} entries")
            good.append(name)
        except Exception as exc:  # noqa: BLE001 - DEAD is the finding, not a crash
            print(f"  DEAD  {name:<26} {type(exc).__name__}: {exc}")
            bad.append(name)
        time.sleep(REQUEST_DELAY)

    print(f"\n{len(good)} live, {len(bad)} dead")
    if bad:
        print("prune from SOURCES: " + ", ".join(bad))

    print("\nchecking sleeper endpoints...")
    print(f"  trending/add: {len(fetch_trending('add', limit=10))} rows")
    fetch_ownership()


def main() -> int:
    if "--check-feeds" in sys.argv:
        check_feeds()
        return 0
    dry = "--dry-run" in sys.argv

    api_key = os.environ.get("AI_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
    sync_token = os.environ.get("SYNC_TOKEN", "")
    if not dry and not sync_token:
        print("::error::sleepers: SYNC_TOKEN is required")
        return 2
    if not api_key:
        # Same posture as the verdicts job: the schedule can be on before
        # the secret exists, and starts producing the night it lands.
        print("::warning::sleepers: AI_API_KEY is not set -- nothing read this run.")
        return 0

    print("fetching the Sleeper player index...")
    index = asyncio.run(players.fetch_index())

    print("\ncollecting feeds...")
    items = collect_items()
    print(f"{len(items)} items in window\n")

    rows, read = build_consensus(items, index, api_key)
    if not rows:
        # An empty push would replace a real list with nothing on a bad
        # night. The stored list keeps serving under its own honest date.
        print("no consensus found this run — leaving the stored list alone")
        return 0

    if dry:
        print(json.dumps({"article_count": read, "players": rows[:40]}, indent=2))
    else:
        push_state(rows, read, sync_token)

    print("\ntop 10:")
    for s in rows[:10]:
        print(
            f"  {s['score']:6.2f}  {s['name']:<24} {s['position']:<3} {s['team']:<3} "
            f"{s['source_count']} sources, {s['trending_adds_72h']} adds"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
