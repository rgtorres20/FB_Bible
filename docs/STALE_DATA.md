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

**TD-lean review: SHIPPED, NOT YET OBSERVED.** `scripts/annotate.py` (consolidated)
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
   *Superseded for the backup question, Aug 21:* the owner flagged these
   as guesses ("backup running list / usage splits not live estimates")
   and asked for the latest wire post on whoever needs picking up after a
   starter goes down. **`/app/nextup` answers both from measured data.**
   `app/feeds/depth.py` orders every team's skill positions by Sleeper's
   '25 opportunity (carries + targets) — usage the stats reducer had been
   storing since August that nothing had ever joined up. The board pairs
   each flagged-out starter with the man behind him, the workload coming
   loose, and the **real newest polled item** about the replacement.
   Injury flags and wire posts are live; depth order and workload are
   measured '25 and labelled so on every row; nothing is projected.
   *Resolved Aug 25:* the **CUFFS table now shows the measured numbers
   too.** `depth.inject_cuffs` joins `usage()` onto its 32 rows at serve
   time, so the rush/route split is computed from real carries and
   targets instead of being typed. One relabel travelled with the data:
   the table said "GL carries · inside the 5" and Sleeper counts
   red-zone attempts inside the 20, so the label moved rather than a
   red-zone figure being filed under a goal-line heading — an unsourced
   number replaced by a mislabelled one is not an improvement. A player
   the stats do not cover reads "no '25 usage", never a zero. What stays
   curated is the judgement around the numbers — who is worth a late
   pick and why — and the tab's stamp now says which half is which.
6. **TARGETS (the Sleepers tab's 19 rows)** — analysts' picks
   transcribed by hand from PFF, Yahoo and Bleacher Report on **Aug 14**,
   frozen there, and carrying no date until `curated.inject` stamped the
   tab on Aug 25.
   *Answered Aug 26, differently than the other rows here.* The owner's
   complaint was not that the rows were old: *"right now it doesnt make
   sense and this list should be editble like we discused"*. Staleness was
   the symptom; the disease was that the tab held **somebody else's** list
   and offered no way to change it. Refreshing the transcription would have
   fixed neither.
   So the tab now opens on **your own list** — a per-user watchlist stored
   beside your ranking lists and league settings (`app/feeds/watchlist.py`,
   `/app/data/sleepers.json`, `POST /app/mine/sleepers`) — and under it a
   thread of **the real polled items mentioning those players**. That
   thread is a *join*, not a search: the poller already tags every item
   with the players it mentions, so this is a lookup against work already
   done, and it renders the item's own headline and link rather than a
   summary of one. Nothing on it can go stale, because nothing on it is
   transcribed.
   The 19 analyst rows are **kept below it, dated and retitled**
   "Analysts' picks · hand-read, not live". Nineteen names somebody
   researched are a reasonable place to start a list from; the failure was
   that they were the *only* list. The app deliberately does not decide who
   your sleepers are — it can say a player is trending or projected above
   his ADP, it cannot say who you believe in, and that judgement is exactly
   what the frozen table was carrying on somebody else's behalf.

7. **weekrev / Team intel / FFBets salaries** — curated estimates, already
   labelled "estimates / no live sheet" in Data health. Plan: revisit when
   the season starts (weekrev is a September feature); salaries have no
   free live source — the honest label stays.
   *Owner flagged Aug 21 ("FFBets salary bets and projection are not
   live").* Confirmed, and it splits into two different answers.
   **DFS salaries cannot go live:** DraftKings and FanDuel publish no
   open API, and scraping their slates is both against their terms and
   fragile — the honest label is the ceiling here. Build-a-team is
   already shelved at serve time, which is why those numbers are not on
   screen. **Projections can:** Sleeper serves
   `/v1/projections/nfl/regular/{season}/{week}` (probed live Aug 21 —
   HTTP 200, same field vocabulary as the season stats). Not built yet;
   it is the largest remaining honest win on that tab.
   *Partially resolved Aug 20:* weekrev's **games** are live — the
   sync-feeds runner pushes ESPN's current-week scoreboard (scores,
   FINAL/clock/kickoff status, broadcast as the only note) to
   /internal/scores and the overlay serves F.weekrev. The high-performer
   column stays the curated seed, passed through, until per-player box
   scores exist to rank honestly (September, Sleeper weekly stats).
   *Partially resolved Aug 18:* Team intel's **usage numbers** (pass rate
   and what was "GL % run") are now measured from Sleeper's '25 season team
   aggregates and injected at serve time, relabelled **"RZ x% run share
   ('25)"** because Sleeper carries no run/pass split inside goal-to-go —
   red-zone run share is the closest number that is real. All 32 teams or
   the page keeps its curated consts (no partial maps). The **'26 win
   projections on the same tab stay curated**, and the Data health row says
   which half is which.

## Checking the app against reality

Added Aug 21, after the owner asked how to improve the AI predictions and
whether a second model would help. The honest answer was that **nothing
had ever checked whether a call was right**, so there was no way to tell
whether any change — a second model, a better prompt, more evidence —
helped or hurt. A second model buys agreement, not accuracy; both read
the same inputs and regress to the same conventional wisdom.

`/app/scorecard` is the check. `app/feeds/scorecard.py` keeps an
**immutable ledger**: every TD lean is snapshotted the moment it is made,
keyed by season, week, player and prop, and an existing key is never
overwritten — not by a line move, not by a re-run, not by a better idea.
A prediction you can edit once you know the answer is not a prediction,
and the sync runs every 15 minutes, so this property is what makes the
record evidence rather than a changing opinion. Grading happens later
against Sleeper's real per-week box scores (endpoint probed live before
anything was scored against it).

The number the page exists for is **calibration**, not the hit rate: a
band that says 78 and hits 33 is overconfidence, and a bare 52% hides it.

Three refusals, each a way the figure could become a lie:

- **No rate over an empty set.** Before Week 1 the page says which games
  it is waiting for. An empty ledger reports `None`, never 0%.
- **Pushes and unplayed games are excluded**, not folded in. A player who
  did not appear stays open — "did not play" is not a wrong call about
  what he would have done.
- **Only falsifiable calls are counted.** Props have lines a box score
  settles. Capsules, wire verdicts, mover reads and matchup previews are
  prose; scoring prose needs an invented rubric and would produce a
  number that looks measured and is not. They stay unscored and the page
  says so.

The ledger lives in its own store key (`fbbible:scorecard`), like the
allowlist, because losing it to a feeds-blob rebuild would not merely
drop data — it would silently reset the accuracy history to "no
evidence", which is the most flattering possible state.

## The enforcement loop

- Data health is the single place freshness is reported, and the overlay
  stamps it from real fetch times — never hardcoded.
- `verify-live.yml` fails loudly if a gone-live surface reverts to its
  curated fallback (news, NBC, Vegas so far). When a surface on the list
  above goes live, add its check in the same commit.
- New surfaces start on this list or start live; a tab that quietly ships
  hardcoded "live" data is the failure mode this project exists to kill.
