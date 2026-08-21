# Weights — architecture

**Status: design. Nothing here is built yet.** Owner ask, Aug 21: *"we have a
few types of weights — one for news wires and another for top-300 draft picks
toward draft analyzer. Sleepers should have a weight based on info given
(website post or a list given by users). Let's take a step back and architect
this the right way."*

That reading is correct, and it names the bug. This document is the design
that follows from it.

## The problem

One slider abstraction is doing three unrelated jobs.

`frontend/index.html:1409` defines a single `SOURCES` array — ten entries, one
`weight` each, one slider each, one percentage each. The percentage is a share
of the weights switched on:

```js
influence(x) = weightOf(x) / Σ weightOf(active) × 100      // :2178, :2187
```

But the entries are not the same *kind of thing*, and almost none of the
weights reach an output:

| Source | Kind | What its weight actually does |
| --- | --- | --- |
| Aggregate ADP, ESPN draft kit, Yahoo top-300 | rank list | Sums into `trusted` |
| My own tiers | rank list | Sums into `own` |
| Team beat writers | usage signal | **Nothing** — on/off only (`:2260`) |
| Route and snap analytics | usage signal | **Nothing** — on/off only (`:2261`) |
| NBC Sports, @AdamSchefter, Rotowire | news wire | **Nothing at all** |

The four that count collapse to one scalar:

```js
srcWeight = 100 × trusted / (trusted + own)                // :1904
blendScore = (1 - w) × player.rank + w × player.adp        // :2250
```

So five of nine active sliders move a bar and change no output. The panel says
*"weight sets how hard it pulls"*. For most rows it does not pull. Under this
repo's **no false positives** rule that is a defect, not a rough edge.

The deeper fault is the category error: a news wire and a top-300 ranking list
cannot share a slider, because they do not share a **unit**, a **consumer**, or
a **truth condition**. Schefter reporting a torn ACL and ESPN ranking a player
73rd are not two amounts of the same substance.

## What already exists (and is good)

The server already has a real news scorer. This design does not replace it — it
plugs weights into it.

- **`app/feeds/impact.py`** — `classify()` buckets an item severe / status /
  positive / noise; `score()` adds category points (`50 / 25 / 15 / -40`) to
  points for *who it is about* (Sleeper `search_rank`, FA status); `order()`
  applies time decay at `DECAY_PER_DAY = 3.0`; `cluster()` folds the same story
  from multiple outlets into one (Jaccard `0.5`, 36h window).
  **Source identity is not part of the score today.**
- **`app/feeds/sources.py`** — 7 polled feeds, each with `tier` (1 = fact,
  2 = analysis) and `budget_hours`. No trust value.
- **`app/feeds/adp.py`** — live FFC ADP blended across 10- and 12-team; sleeper
  finds from a *position-adjusted* ADP-vs-rank gap (`SLEEPER_MIN_GAP = 25`);
  and `_article_finds()`, which picks up wire items containing "sleeper" that
  have a tagged player.
- **`app/feeds/scorecard.py`** — an immutable ledger that records a call when
  it is made and grades it later against real box scores.

Two of these matter enormously for the design. `cluster()` already knows when
three outlets said the same thing. And the scorecard already knows how to grade
a claim. Both are currently unused by any weighting.

## The design: three weight families

Three separate registries, three units, three consumers. One canonical module —
`app/feeds/weights.py` — for the same reason `app/leagues.py` is the only place
league facts live: a number that exists in two places will eventually disagree
with itself.

`sources.py` stays *where to fetch*. `weights.py` becomes *how much to believe*.

---

### 1. Wire trust — news

**Unit:** a multiplier on an impact score.
**Consumer:** what surfaces in Alerts and the news overlay, and in what order.

```
final = impact.score(item) × wire_trust(source_key) × corroboration(n) − decay(age)
```

Two changes to `impact.py`:

- `order()` takes the source's trust into account, so a Schefter status post
  outranks an identical-category post from a weaker outlet.
- `cluster()` returns **how many outlets carried the story**. Today duplication
  is treated purely as noise to be folded away. It is also evidence: three
  independent outlets reporting the same injury is a stronger claim than one.
  Corroboration should *raise* the score, sub-linearly (`1 + k·log n`), and the
  highest-trust outlet's copy should be the one displayed.

Trust here is about *reliability of report*, and it is separable from tier —
tier says fact-vs-opinion, trust says how often this outlet is right and first.

---

### 2. Board trust — rankings into the draft analyzer

**Unit:** a share in a weighted rank aggregation.
**Consumer:** the order of the Draft analyzer board.

Replace the single rank↔ADP interpolation with an aggregation over N lists:

```
blended_rank(p) = Σ (wᵢ × rankᵢ(p)) / Σ wᵢ        over lists that rank p
```

Only genuine **rank lists** belong here: Aggregate ADP (live FFC), ESPN draft
kit, Yahoo consensus top-300, Sleeper `search_rank`, and My own tiers. The
wires do not — that is the category error, fixed.

The trap is **missing players**. A source that does not rank a player must not
be read as ranking him 0, and must not silently drop him. Renormalize over the
lists that actually rank him, and surface how many did — a player ranked by one
list out of five is a different claim from one ranked by all five, and the board
should be able to say so.

This subsumes today's behaviour: current `srcWeight` is the two-list case.

---

### 3. Sleeper evidence

**Unit:** confidence in a claim about one player.
**Consumer:** the sleeper list — what appears, and how it is ordered and marked.

This is the one the owner framed most precisely: *weight based on the info
given*. A sleeper claim has **provenance**, and provenance sets confidence.

The evidence kinds already present in the codebase:

| Evidence | Where it comes from | Why it ranks where it does |
| --- | --- | --- |
| **Measured ADP gap** | `adp.py`, position-adjusted | Computed from real draft rooms — strongest, because nobody's opinion is in it |
| **Measured usage** | `depth.py`, Sleeper '25 opportunity | Also measured; not yet joined to sleepers |
| **Article mention** | `_article_finds()` | Someone published it — trust flows from wire trust (family 1) |
| **User list** | ★ button, `/app/mine` documents | The owner's own call; high trust, zero corroboration |

```
confidence = evidence_base(kind) × source_trust × corroboration × recency
```

The key property: this makes evidence kinds **comparable**, so a sleeper backed
by a measured 30-pick gap can outrank one backed by a listicle, and the card can
say which it is instead of presenting both as "Sleeper find".

---

## The part that makes the weights honest

Every weight above is, today, an opinion typed into an array. The app already
owns the machinery to turn them into measurements.

A sleeper call is the same shape as a TD lean: a claim, made at a known time,
gradeable later against real production. `scorecard.py` already records
immutably and grades against Sleeper box scores, and already reports
**calibration** rather than a bare hit rate.

So: record sleeper and wire-driven calls into the ledger with their evidence
kind and source attached. After a few weeks of real games, the ledger can answer
*which sources and which evidence kinds were actually right* — and the defaults
stop being declared and start being earned.

That is the argument for doing this properly rather than patching the sliders:
it is the difference between a control panel and a measurement.

## Where things live

| Piece | Home | Note |
| --- | --- | --- |
| The three registries + combine functions | `app/feeds/weights.py` (new) | Pure, no I/O, unit-testable |
| Wire trust applied | `app/feeds/impact.py` | `order()`, `cluster()` |
| Board aggregation | `app/feeds/board.py` + serve-time inject | `index.html` stays pristine |
| Sleeper confidence | `app/feeds/adp.py` | Finds carry `evidence` + `confidence` |
| Per-user overrides | own Redis key, per email | Same pattern as the allowlist and leagues |
| Editor UI | `/app/weights`, built with `skin.head()` | Add to `tests/test_navigation.py` |

Constraints that bind (from CLAUDE.md): no background tasks, no local disk, no
in-process caches — both `uvicorn` and Vercel must keep working. Any surface
that goes live gets a `verify-live.yml` check **in the same commit**.

## Phasing

Ordered so that nothing ships claiming an influence it does not have.

1. **Stop lying.** Split the panel into three labelled groups and disable the
   sliders that feed nothing, each with a one-line statement of what it changes.
   Small, and it closes the false-positive defect immediately.
2. **Wire trust.** Trust values + corroboration in `impact.py`. Self-contained,
   and the Alerts board shows the effect straight away.
3. **Board aggregation.** Replace the scalar blend with weighted rank
   aggregation. The riskiest change — it reorders the draft board — so it wants
   the mock-draft engine's headless test as its check.
4. **Sleeper evidence.** Evidence kinds and confidence on every find; the card
   states its provenance.
5. **Grade it.** Sleeper calls into the ledger; calibration by source and by
   evidence kind; defaults derived from the record.

Steps 1 and 2 are independently useful and do not depend on 3–5.

## Open questions for the owner

1. **Do wire weights belong to the user at all?** Trust in Schefter is close to
   a fact about the world, not a preference. Options: ship measured defaults and
   let users nudge; or keep wire trust owner-only and give users only board
   trust and sleeper evidence, which are genuinely about their league and taste.
2. **How much should corroboration count?** Three outlets on one story — worth
   1.5× a single report, or 2×?
3. **Should a user's own tier list be able to win outright?** Today `srcWeight`
   can go to 0 ("My tiers only"). Keep that escape hatch in the N-list model?
