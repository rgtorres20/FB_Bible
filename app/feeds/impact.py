"""Score, annotate and dedupe wire items by impact on a fantasy board.

Validation against the live feed showed the two failure modes this exists
for: "Aikman gets Brady-like limits for MNF broadcasts" tagged Tom Brady
(QB·FA) and sat in the feed as if it mattered, while the Pearce suspension
arrived three times from three outlets. A chronological wire treats those
identically; a draft tool must not.

Three plain-code stages, no model calls:

  classify()  keyword buckets -- severe / status / positive / noise
  score()     keywords + who it's about (Sleeper search_rank, FA status)
  cluster()   folds the same story from multiple outlets into one item

Scores are annotations, not censorship: /api/feeds carries everything with
its score attached; only the page overlay drops negative-scoring items, and
what was dropped is countable there.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

# --- keyword buckets -------------------------------------------------------
# Word-boundary regexes, matched against title + summary lowercased. Buckets
# are checked in this order; first hit wins the category label, but severe
# always outranks a stray positive word in the same sentence.

SEVERE = re.compile(
    r"\b(torn|tore|tears?\b|acl|achilles|mcl\b|pcl\b|fracture[sd]?|broken|"
    r"surgery|season.ending|out for (the )?(season|year)|ruled out|"
    r"suspend(ed|sion)|arrest(ed)?|carted off|ir\b|injured reserve|pup list|"
    r"waived|released|retir(es?|ing|ement))\b"
)
STATUS = re.compile(
    r"\b(questionable|doubtful|day.to.day|limited|hamstring|groin|ankle|"
    r"concussion|knee|shoulder|calf|quad|soft.tissue|soreness|misses? practice|"
    r"held out|did not practice|dnp\b|scratched|sits? out|holdout|holding out|"
    r"injur(y|ed)|banged up|mri\b|x.rays?)\b"
)
POSITIVE = re.compile(
    r"\b(returns? to practice|activated|cleared|full (practice|participant)|"
    r"expected back|good sign|no structural|avoided serious|debut|first start|"
    r"named (the )?starter|wins? the job|breakout|impress(es|ed|ive))\b"
)
NOISE = re.compile(
    r"\b(broadcasts?|booths?|announcers?|jerseys?|uniforms?|stadiums?|tickets?|"
    r"ownership|lawsuits?|settle[sd]?|financing|sponsors?|documentar(y|ies)|"
    r"podcasts?|hall of fame|retired numbers?|coach of|front office|"
    r"general manager|schedule release)\b"
)

_CATEGORY_ORDER = ("severe", "status", "positive", "noise")


def classify(text: str) -> str | None:
    """First matching bucket, with severe taking precedence."""
    lowered = text.lower()
    if SEVERE.search(lowered):
        return "severe"
    if STATUS.search(lowered):
        return "status"
    if POSITIVE.search(lowered):
        return "positive"
    if NOISE.search(lowered):
        return "noise"
    return None


# --- scoring ---------------------------------------------------------------

_CATEGORY_POINTS = {"severe": 50, "status": 25, "positive": 15, "noise": -40, None: 0}


def _best_rank(item: dict, ranks: dict[str, int] | None) -> int | None:
    """Lowest (best) Sleeper search_rank among tagged players."""
    best = None
    for player in item.get("players") or []:
        rank = (ranks or {}).get(player.get("id", ""))
        if rank is not None and (best is None or rank < best):
            best = rank
    return best


def _rank_points(rank: int | None) -> int:
    if rank is None:
        return 0
    if rank <= 100:
        return 40
    if rank <= 200:
        return 25
    if rank <= 400:
        return 10
    return 0


def score(item: dict, ranks: dict[str, int] | None = None) -> dict:
    """Attach {score, category, top_rank} to a copy of the item."""
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    category = classify(text)
    players = item.get("players") or []

    points = _CATEGORY_POINTS[category]
    rank = _best_rank(item, ranks)
    points += _rank_points(rank)

    if not players:
        points -= 10

    # A free agent in a story with no fantasy substance is the Tom Brady
    # case: correct name match, zero draft relevance.
    if players and all(not p.get("team") for p in players) and category in (None, "noise"):
        points -= 30

    return {**item, "impact_score": points, "impact_category": category, "top_rank": rank}


def annotate(item: dict) -> str:
    """A short factual line for the page's WHAT IT MEANS column.

    Prefixed "Auto:" so it never masquerades as the owner's judgement --
    curated threads carry lines like "Off the LB board in both leagues",
    and this is not that.
    """
    players = item.get("players") or []
    category = item.get("impact_category")
    rank = item.get("top_rank")

    who = players[0]["name"] if players else None
    ranked = rank is not None and rank <= 400
    rank_note = f" · top-{(((rank - 1) // 100) + 1) * 100} player" if ranked else ""

    if category == "severe" and who:
        return f"Auto: availability risk — {who}{rank_note}"
    if category == "status" and who:
        return f"Auto: injury/status watch — {who}{rank_note}"
    if category == "positive" and who:
        return f"Auto: positive sign — {who}{rank_note}"
    if who and rank is not None and rank <= 200:
        return f"Auto: news on {who}{rank_note}"
    return ""


# --- reading order ---------------------------------------------------------

# How fast a story's claim on the top of the page decays. 3 points a day means
# a severe story on a ranked player (~75-90 points) outranks fresh routine news
# for about two weeks -- draft prep still needs it -- while yesterday's
# "questionable" sinks beneath anything that happened this morning.
DECAY_PER_DAY = 3.0
# Undated items cannot be scored for age; treat them as a week old so they
# neither float as breaking news nor vanish outright.
UNDATED_AGE_DAYS = 7.0


def _age_days(item: dict, now: datetime) -> float:
    published = _parse(item.get("published"))
    if published is None or published.tzinfo is None:
        return UNDATED_AGE_DAYS
    return max((now - published).total_seconds(), 0.0) / 86400.0


def order(items: list[dict], now: datetime) -> list[dict]:
    """Impact-ranked reading order: score decayed by age, newest first on ties.

    The wire arrives chronological; this is the "rank by impact on your board,
    not just time" pass. Scores must already be attached (see score())."""
    timed = sorted(items, key=lambda i: i.get("published") or "", reverse=True)
    return sorted(
        timed,
        key=lambda i: i.get("impact_score", 0) - DECAY_PER_DAY * _age_days(i, now),
        reverse=True,
    )


# --- cross-source dedupe ---------------------------------------------------

_WORD = re.compile(r"[a-z0-9']+")
_STOP = frozenset(
    "the a an and or of for to in on at with by vs after before as is are was".split()
)
CLUSTER_WINDOW = timedelta(hours=36)
JACCARD_THRESHOLD = 0.5


def _tokens(title: str) -> frozenset[str]:
    return frozenset(w for w in _WORD.findall(title.lower()) if w not in _STOP)


def _parse(iso: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(iso) if iso else None
    except ValueError:
        return None


def _same_story(a: dict, b: dict, ta: frozenset, tb: frozenset) -> bool:
    pa, pb = _parse(a.get("published")), _parse(b.get("published"))
    # Only compare when both stamps carry a timezone: naive-vs-aware
    # subtraction raises, and one publisher drifting to naive ISO must not
    # 500 the whole overlay. Unknown window -> fall through to the
    # content checks rather than assuming same or different.
    if pa and pb and pa.tzinfo and pb.tzinfo and abs(pa - pb) > CLUSTER_WINDOW:
        return False
    if ta and tb:
        union = len(ta | tb)
        if union and len(ta & tb) / union >= JACCARD_THRESHOLD:
            return True
    # Same player, same category: two outlets writing up the same event with
    # different headlines ("Pearce suspended 8 games" / "Falcons LB banned").
    ids_a = {p.get("id") for p in a.get("players") or []}
    ids_b = {p.get("id") for p in b.get("players") or []}
    if ids_a & ids_b and a.get("impact_category") == b.get("impact_category") is not None:
        return True
    return False


def cluster(items: list[dict]) -> list[dict]:
    """Fold duplicates. Keeps the best-tier, earliest telling of each story
    and records the other outlets on it as `also_from`."""
    kept: list[dict] = []
    token_cache: list[frozenset] = []

    for item in items:
        tokens = _tokens(item.get("title", ""))
        for i, existing in enumerate(kept):
            if _same_story(existing, item, token_cache[i], tokens):
                also = existing.setdefault("also_from", [])
                name = item.get("source_name", "?")
                if name != existing.get("source_name") and name not in also:
                    also.append(name)
                # Prefer the better tier as the kept telling. The credit
                # list must never contain the kept item's own outlet --
                # "ESPN (also: ESPN, CBS)" credits nobody.
                if item.get("tier", 9) < existing.get("tier", 9):
                    credits = also + [existing.get("source_name", "?")]
                    item["also_from"] = [
                        s
                        for i2, s in enumerate(credits)
                        if s != item.get("source_name") and s not in credits[:i2]
                    ]
                    kept[i] = item
                    token_cache[i] = tokens
                break
        else:
            kept.append(dict(item))
            token_cache.append(tokens)
    return kept
