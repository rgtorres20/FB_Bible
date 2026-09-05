# The AI layer — what it does and what it does not

Owner ask, Aug 21: *"we need to also look at AI predictions, I want to
understand what is going on there."* Written from the code, with the
claims checked rather than recalled.

**One sentence:** the AI writes short labelled prose next to numbers the
app already computed, and it changes nothing — not a rank, not a price,
not a pick.

## What it is

| | |
| --- | --- |
| Provider | **Google AI Studio (Gemini)**, free tier, no card |
| Endpoint | its OpenAI-compatible chat-completions API, so any OpenAI-shaped provider is a config change, not a code change |
| Model | `models/gemini-flash-latest`, with `models/gemini-flash-lite-latest` as fallback |
| Configurable by | `VERDICT_API_URL`, `VERDICT_MODEL`, `VERDICT_FALLBACK_MODEL` |
| Secret | `AI_API_KEY`. Absent, the job no-ops with a warning rather than failing |
| Where it runs | an hourly GitHub Actions runner — **never** on Vercel, which has no background tasks |
| Rate | one request per hour; coverage accumulates over days |

Not Anthropic, despite this repo being built with Claude. Owner's call,
Aug 15, on cost.

## The four things it writes

1. **Player capsules** — one sentence per player synthesising his rank,
   live ADP, '25 usage, injury flag and newest wire item. Shown on the
   top-300 alert board and in the mock room's why-panel, prefixed
   **"AI angle:"**.
2. **Matchup previews** — one read per game from the Vegas slate, the
   '25 team-offence profile and, since Sep 5, each side's projected top
   scorers for the week (`projected_top`: Rotowire's line via Sleeper,
   scored under the owner's first league, with the flag or practice
   status Sleeper carries). Appended to a schedule row prefixed
   **"AI preview:"**, and shown again on the ranked game stack.
3. **Wire verdicts** — a one-line take on the newest wire items.
4. **Week review prose** — commentary beside live scores. The scores
   themselves are facts and never model output.

## The grounding rule

**The model never recalls a number; it only reads ones we fetched.**

Every prompt is assembled server-side from the app's own store, so each
figure in it came out of a feed we polled. The hourly script relays that
work list — it does not let the model go and find data, and there is no
browsing, no tool use, no retrieval.

This is the guard against the obvious failure: a model confidently
stating a stat line that was never true.

## What it does NOT do

This is the part worth being precise about, because "AI predictions"
sounds like it drives something. It does not.

- **It does not touch any ranking.** Not ADP, not the draft board order,
  not the blended top list, not the IDP board. Checked: no AI module is
  imported by `board.py`, `adp.py`, `ranklists.py`, `leagues.py`,
  `idp.py`.
- **It does not influence a single mock-draft pick.** The capsule reaches
  the mock room as `p.cap` and is read in exactly one place —
  `mock.py:815`, which renders it into the why-panel. The pick logic
  never reads it. (The `cap` at lines 519 and 602 is a positional roster
  cap, an integer, and unrelated.)
- **It does not affect league scoring.** `score_offense`, `score_idp` and
  `score_dst` are arithmetic over stored stats.
- **It is not graded.** `scorecard.py` deliberately leaves capsules,
  verdicts, mover reads and previews **unscored**: they are prose, and
  inventing a rubric to score prose would produce a number that looks
  like a measurement and is not one.
- **It never speaks as the owner.** Every surface is labelled, which is
  why the prefixes exist.
- **It is not a prediction engine.** The app's actual predictions — the
  TD leans — are the owner's own calls, adjusted by live Vegas implied
  totals. The AI may add a labelled clause beside one; it does not make
  the call, and the ledger records the owner's number.

So "AI predictions" is a misnomer for what is really **AI colour
commentary on measured numbers.**

## What to watch

- **Model aliases drift.** `models/gemini-flash-latest` is whatever
  Google currently points it at, so the writing can change under us
  without a deploy. Pinning a version trades that for the opposite risk —
  the pinned one being retired. This repo has already been burned once:
  CLAUDE.md's validation gate exists because the AI layer was built
  against a provider retired two weeks earlier and then pointed at a
  model that no longer existed. **Never trust a model name you have not
  asked the live endpoint about.**
- **Free tier limits.** A few hundred requests a day against one per
  hour, so there is headroom — but a burst would hit it.
- **Nothing measures whether the prose is any good.** That is a
  deliberate choice, not an oversight, but it means quality drift would
  be invisible. If that matters later, the honest fix is not to score the
  prose but to grade the *decisions it sits next to*, which the scorecard
  already does.

## If you wanted it to do more

The obvious upgrade is not a better model, it is a **second opinion that
gets graded**. The scorecard already records a call when it is made and
settles it against real box scores; an AI call recorded the same way
would earn or lose trust on the record instead of by assertion. That is
the disagreement-signal idea from the weights work, and it stays unbuilt
on purpose — it needs a few weeks of real games behind it before the
calibration means anything.
