# Stale-data audit and plan

Project rule (also in CLAUDE.md): **every user-facing surface is either
live-polled, the owner's own judgement, or curated facts wearing an honest
as-of stamp.** Nothing may claim freshness it does not have, and nothing
fabricates a judgement or a number to look complete — an empty truthful
section beats an invented one (no false positives).

Audited Aug 15, every tab and const in the page plus every feeds.json key.

## Live today (auto-updating, no action needed)

| Surface | Source | Cadence |
|---|---|---|
| News & posts | ESPN, Yahoo, Rotowire, PFT, CBS wire | ~hourly sync |
| NBC player news | Rotoworld page scrape | ~hourly sync |
| Draft analyzer ADP column | FFC live drafts, per league size | ~hourly |
| Scout finds: movers / sleeper gaps | FFC live drafts + Sleeper ranks | ~hourly + daily snapshots |
| Vegas lines (FFBets · Predictions) | ESPN scoreboard odds | ~hourly sync (Aug 15) |
| TD-lean confidence (FFBets) | implied-total movement vs openers | every request (Aug 15) |
| Week 1 schedule (kickoff/teams/TV) | ESPN scoreboard | ~hourly sync (Aug 15) |
| Trending adds/drops, injury flags | Sleeper API, fetched by the page | on page load |
| Team intel usage reads (pass rate + RZ run share) | Sleeper '25 season team aggregates | weekly refetch, injected per request (Aug 18) |
| Top-300 alert board (`/app/alerts300`) | Sleeper ranks + stored wire + labelled AI/Auto lines | every request (Aug 18) |
| Data health stamps | overlay-stamped per feed | every request |
| Out & returning wire stamps | latest wire mention per player | every request |
| AI draft verdicts (news tab) | Google AI Studio over the newest wire items | hourly (live since Aug 18) |

## The AI layer — what is live and what is only shipped

This table used to list verdicts as live and hourly. They had never
worked: the job targeted **GitHub Models, retired 2026-07-30**, so every
run got HTTP 410 Gone. A failed model call exited 0, so the workflow
reported success and nobody saw it. The page itself never lied — with no
verdicts stored it renders the rule-based `Auto:` line — but this document
did, which is the exact failure the no-false-positives rule exists to
prevent.

Both bugs that kept it invisible are fixed: the sync was separately
deleting stored verdicts on every run, and a permanent endpoint failure
was indistinguishable from a rate limit (it now exits non-zero and
annotates).

**Provider: Google AI Studio** (owner's call, Aug 15) — free tier, no
card, through its OpenAI-compatible endpoint so the pipeline stays
ordinary chat-completions. The key lives in the `AI_API_KEY` repository
secret (`GEMINI_API_KEY` is read too). Model is the moving alias
`models/gemini-flash-latest`, deliberately: pinned point versions get
retired out from under the job, which is how the last provider broke.

**Wire verdicts: LIVE.** First real output Aug 18 — 18 items in, 13
verdicts stored, 8 rendering on the news tab. The hourly schedule has run
green since (latest observed: run 39, 2026-08-18 05:05 UTC).

**TD-lean review: SHIPPED, NOT YET OBSERVED.** `scripts/review_predictions.py`
checks each curated lean against that team's live implied total and posts
an "AI check:" clause to `/internal/pred-reviews`; the lean and its
confidence are never touched. The workflow step landed on `main` at 05:16
UTC on Aug 18, *after* every AI-verdicts run to date — so no run has
executed it. It is deliberately **not** in the live table above until a
run shows the step exiting 0 and a Predictions row carries the clause.
Code is tested and the endpoint validates against the curated lean names;
what is missing is proof, and proof is what this table is for.

## Still curated — with the honest state and the plan

Ordered by how much staleness actually costs.

1. ~~**Week 1 schedule**~~ — RESOLVED Aug 15. Kickoff day/time (Central),
   team names and network now come from the stored scoreboard payload and
   swap into the served WEEK1 const; the owner's per-game notes ride along
   by matchup, and ESPN's broadcast field falls back to the curated network
   rather than inventing one. Weeks 2–18 remain a Phase 3 item (the tab
   only renders Week 1 today).
2. ~~**PREDICTIONS (TD model leans)**~~ — RESOLVED Aug 15 (owner's call:
   compute live). The leans stay the owner's Aug-14 judgement — never
   auto-flipped — while confidence now shifts with each team's live
   implied-total movement vs the curated openers (±2 conf points per
   implied point, clamped 35–90, sub-half-point moves ignored as book
   noise), and adjusted rows annotate the move. A team with no posted or
   no baseline line stays exactly as curated: adjusting on a guess would
   be a false positive.
3. **OUTLIST / RETURNING content** — statuses and notes are curated; the
   wire stamps (Aug 15) now show per-row age honestly, and Sleeper injury
   flags catch status flips in Alerts. Plan: keep curated (the notes are
   judgement), refresh at chat-sync, rely on stamps for honesty.
4. **Alerts tab** — curated judgements over live-flagged players. The
   judgement *is* the product (see PHASE2_SPEC); it should never be
   auto-generated. Plan: stays curated by design; AI drafts already
   overlay as clearly-labelled drafts, never as the owner's calls.
5. **CUFFS (handcuff usage splits)** and **RUN_EDGES (run rates vs run
   defense)** — '25-season estimates, clearly labelled. They do not rot
   until games are played. Plan: Phase 3, compute from nflverse play-by-play
   once there is a database; until then the Data health rows keep calling
   them estimates.
6. **weekrev / Team intel / FFBets salaries** — curated estimates, already
   labelled "estimates / no live sheet" in Data health. Plan: revisit when
   the season starts (weekrev is a September feature); salaries have no
   free live source — the honest label stays.
   *Partially resolved Aug 18:* Team intel's **usage numbers** (pass rate
   and what was "GL % run") are now measured from Sleeper's '25 season team
   aggregates and injected at serve time, relabelled **"RZ x% run share
   ('25)"** because Sleeper carries no run/pass split inside goal-to-go —
   red-zone run share is the closest number that is real. All 32 teams or
   the page keeps its curated consts (no partial maps). The **'26 win
   projections on the same tab stay curated**, and the Data health row says
   which half is which.

## The enforcement loop

- Data health is the single place freshness is reported, and the overlay
  stamps it from real fetch times — never hardcoded.
- `verify-live.yml` fails loudly if a gone-live surface reverts to its
  curated fallback (news, NBC, Vegas so far). When a surface on the list
  above goes live, add its check in the same commit.
- New surfaces start on this list or start live; a tab that quietly ships
  hardcoded "live" data is the failure mode this project exists to kill.
