# Unit: wire

**One worked example of a unit contract.** If this shape is right, the
other units get one of these. If it is the wrong size, change it here
first — writing seven of the wrong thing is worse than writing none.

An agent should be able to own this unit having read only this page and
the four modules it names. Nothing here requires knowing what the app
looks like, what a league is, or how a page is rendered.

---

## What it owns

Turning outside news into scored, deduped items the rest of the app can
rank.

| Module | Job |
| --- | --- |
| `app/feeds/sources.py` | The registry: which feeds, their tier and freshness budget, their required attribution |
| `app/feeds/rss.py` | Parse an RSS/Atom body into items |
| `app/feeds/rotoworld.py` | Same, for the one feed that is not RSS-shaped |
| `app/feeds/poller.py` | Fetch the registry, merge with what is stored, stamp `first_seen` |
| `app/feeds/impact.py` | Classify, score, time-decay and cluster the merged items |
| `app/feeds/injury.py` | Extract injury status from item text |

## Contract

**In:** HTTP response bodies (bytes) and the previously stored feed blob.
Nothing else. No league, no user, no page.

**Out:** a list of item dicts. The fields other units and surfaces rely
on — changing or dropping one of these is a breaking change:

```
id            stable per story; guid, else link, else title
title         plain text, entities decoded, tags stripped
summary       plain text, same treatment
link          canonical URL
published     UTC ISO-8601, or None — never a guessed "now"
source        registry key
players       [{name, position, team}] tagged by the player index
category      severe | status | positive | noise | None
score         int; higher is more relevant to a draft board
first_seen    UTC ISO-8601, stamped once and never rewritten
```

**Two invariants that are the whole point of the unit:**

1. **`published` may be `None`.** An item with no date is kept, sorted
   last, and never stamped with the fetch time. A guessed date is a
   fabricated fact, and this repo does not print those.
2. **`score` annotates, it does not censor.** `/api/feeds` carries
   everything with its score attached; only the page overlay drops
   negative-scoring items, and what was dropped stays countable there.

## Fence

May import: the kernel only — `sources`, `players`, `store`, `config`.

May **not** import: `adp`, `usage`, `odds`, `ai`, `scoring`, or any
surface module (`render`, `idp`, `mock`, `nextup`, `accuracy`,
`cheatsheet`, `alerts300`, `page`). Enforced by
`tests/test_boundaries.py` — a breach fails the build, it is not a
convention anyone has to remember.

Owns these test files: `tests/test_sources.py`, `tests/test_rss.py`,
`tests/test_poller.py`, `tests/test_poller_fetch.py`,
`tests/test_impact.py`, `tests/test_feeds.py`.

## Acceptance check

How to tell the unit works **without reading its code**:

```bash
/usr/local/bin/python3 -m pytest -q tests/test_sources.py tests/test_rss.py \
    tests/test_poller.py tests/test_poller_fetch.py tests/test_impact.py
```

Then the two properties that matter more than any single test:

- **A dead feed is distinguishable from a quiet day.** A source returning
  404 must surface as a stale source, not as "no new items". This is
  called out in `sources.py`'s own docstring as the failure the registry
  exists to prevent.
- **The same story from three outlets is one item, and knows it came from
  three.** `cluster()` folds duplicates; the count is evidence, not
  noise (see [../WEIGHTS.md](../WEIGHTS.md)).

Live: `scripts/verify_live.py` checks the served feed. A change here that
passes unit tests and breaks the live wire will show up there — read the
log, not the badge.

## Known issues

- **Double-escaped markup leaks tags into text.** `rss._clean` strips
  tags *before* unescaping, so `&amp;lt;b&amp;gt;` survives as a visible
  `<b>` in a headline. Yahoo's feed really does double-escape (see the
  `Jets&amp;#39;` case in `tests/test_feeds.py`), so this is a live
  shape, not a hypothetical. Cosmetic today — `alerts300` escapes on the
  server-rendered path — but the browser-side renders were not audited.
  Found Aug 21, not yet fixed.

## Open work

- Wire trust: a per-source multiplier on `impact.score`, and
  corroboration from `cluster()` raising confidence rather than being
  discarded. Designed in [../WEIGHTS.md](../WEIGHTS.md), **not built**.
  Owner's call, Aug 21: wire trust is **not** user-editable — it ships as
  measured defaults, because how often an outlet is right and first is a
  fact about the world, not a preference.
