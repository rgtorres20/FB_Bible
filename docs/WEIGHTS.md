# Weights — architecture

**Status: design. Nothing here is built yet — but the design is now closed:
all four open questions were decided by the owner on Aug 21 (see *Decided*).** Owner ask, Aug 21: *"we have a
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

## Decided (owner, Aug 21)

**1. Who owns each family.** Users get **board trust** and **sleeper
evidence** — the two that are genuinely about their league and their
taste. **Wire trust is not user-editable**: how often an outlet is right
and first is a fact about the world, not a preference, so it ships as
measured defaults.

**2. Corroboration applies to the wire only.** Three outlets reporting
the same injury is stronger evidence than one. Three ranking lists
agreeing on a player is *not* corroboration — it is the mean, and the
rank aggregation already computes it. There is no corroboration term in
board trust.

**3. How much corroboration is worth: strictly less than 2×, so 1.5×.**
Not a taste call — the existing scale forces it. `impact.py` scores
categories at severe 50 / status 25 / positive 15. If corroboration could
multiply by 2.0, three outlets on a *status* item (25 × 2 = 50) would tie
a *severe* single report, and anything above 2.0 would outrank it. That
is wrong: five outlets confirming a player is questionable must never
outrank one credible report of a torn ACL.

So the ceiling is `50/25 = 2.0`, exclusive. `1 + 0.5·log₂(n)` gives
1.0 / 1.5 / 1.79 / 2.0 for 1 / 2 / 3 / 4 outlets — which crosses the
ceiling at four. Either clamp it below 2.0 or use a gentler curve; the
test to write first is the constraint, not the formula:

```
a corroborated `status` item never outranks a single-source `severe` item
```

Write that test, then pick whichever curve passes it.

**5. News wires get no weights at all — they are a view, not an input.**

Owner, Aug 21: *"news sources just are what i want to view and i want to
limit the duplicates ... just needs to log info first and add to the
list."*

That deletes the wire-trust family rather than deferring it, and
simplifies the design from three families to two. A news feed is
something you read; it was never a ranking input, and weighting it was
over-design on my part. What the wire actually owes the owner is:

- **Which outlets show up** — an on/off view filter, no weights.
- **One row per story** — the same report from four outlets is one entry,
  with the others credited.
- **The first telling wins.** Whoever reported it first is the row that
  survives. Being first is a *fact*; "which outlet do we rate highest"
  was a judgement nobody asked for.

Corroboration survives only as *information* on the row (`also_from` —
who else carried it), never as a multiplier. Decisions 2 and 3 above
described a corroboration term and a ceiling derived from the category
scale; both are moot now, and are kept only as the record of how the
number would have been bounded had one been needed.

Built Aug 21: `impact.cluster()` now keeps the earliest telling. It had
two problems, both found by asking what it actually did rather than what
it said:

- It kept whichever telling it encountered first, and `poller.merge`
  sorts newest-first — so it kept the **newest** while its docstring
  claimed the **earliest**. The comparison is explicit now.
- It preferred a better-tier outlet over an earlier one, which is the
  weighting this decision removes.

Undated items sort last, never first: an item with no date has no claim
to being first because it has no claim at all.

**Still open on the wire:** the source toggles do not filter anything.
Not weights — nothing. There are zero references to `srcOn.s1/s2/s8/s7`
in the page, so switching an outlet off changes no row. Making them a
real view filter is a design-side change; the panel currently labels them
`not wired`, which is at least honest.

**4. The escape hatch survives, but ADP comes out of the blend.**

Today `srcWeight → 0` ("My tiers only") zeroes ADP, which conflates two
different questions:

- **Your tier list answers "who is better."** That is an opinion, and it
  is yours. It should be able to win outright — a tool that overrides
  the owner is a worse copy of the market.
- **ADP answers "when will he be gone."** That is not an opinion. It is a
  measurement of what the other nine or eleven managers will do. Zeroing
  it does not remove someone else's bias; it deletes information you need
  regardless of your opinions, and you reach in round 3 for a player who
  would have lasted to round 7.

So they do not belong on the same control. ADP is not a competing
ranking — it is an **availability column**.

The N-list model also makes the current behaviour newly dangerous. Under
the old two-list blend a player with no ADP fell back to `b.rank`, so
there was always a number. Under renormalization-over-present-lists, a
player ranked by *zero* active lists has an undefined rank — at "my tiers
only" that is every kicker, every defender and every late flier the owner
never personally ranked. This repo's leagues make it worse: FFC's ADP
carries no individual defenders at all, so eight starting slots in NDDPL
and RED_EYE are already thin before anyone moves a slider.

Decided:

1. **Rank blend** — ESPN, Yahoo, Sleeper, own tiers. Any may go to zero,
   including all-but-mine. The escape hatch is preserved, and doubles as
   a diagnostic: flipping between "market only" and "mine only" shows
   exactly where the owner disagrees with consensus.
2. **ADP is not in that blend.** Always present, never weighted. It
   drives the availability column, the reach/value flags, and the mock
   room's simulation of when players actually go.
3. **A coverage floor.** A player ranked by none of the active sources is
   ordered by ADP and *labelled* "unranked by your sources" — visible,
   never silently sunk to the bottom as though he were bad. No invented
   rank: say there isn't one.

The test to write **before** any of this is built:

```
with only my tiers active, every player on the board still has a defined
position, and the ones I never ranked are marked as such
```

If that fails, the escape hatch is broken whatever the sliders say.

## Still open

Nothing. The four decisions above close the design; what remains is
building it, in the order under *Phasing*.
