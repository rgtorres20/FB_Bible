# Phase 2 — Yahoo league link

The spec for this repo, carried over from the Fantasy Bible blueprint
(`Tab Blueprint.dc.html`, page 2 of the design project).

## The blueprint card, verbatim

> **2 · Yahoo league link**
>
> OAuth to the Yahoo Fantasy API: live rosters, draft results, opponent picks
> for f1/192426 and f1/811739. Needs a small server (token exchange) — first
> piece that leaves the browser.
>
> **FIXES:** MANUAL ROSTER/PICK ENTRY · **EFFORT:** SMALL BACKEND ·
> **WHEN:** BUILDING FOR REAL

## Where this sits in the plan

| Phase | What | Status |
|---|---|---|
| 0 | Player IDs — the foundation | Done (in-app) |
| 1 | Live sync — Sleeper API | Done (in-app, no backend) |
| **2** | **Yahoo league link** | **This repo** |
| 3 | Scheduled jobs + notifications | Next — needs this server |
| 4 | Real projections & salaries | Later |
| 5 | Structure — split the monolith | Partially done in-app |

Phase 2 is the first piece that leaves the browser. Phase 3 ("move the sync
spine server-side: cron jobs poll the feeds on their budget intervals, write to
a database, and the Settings push rules finally deliver via web push") lands on
top of this same service — which is why the token store is an interface and
there's a Dockerfile alongside the Vercel config.

## Scope

In scope:

- Three-legged Yahoo OAuth2, including refresh.
- Encrypted, swappable token storage (works on serverless).
- Read endpoints for: leagues, teams, live rosters, draft results, scoreboard,
  transactions.
- Flattening Yahoo's JSON so the browser app never learns its shape.

Explicitly out of scope for Phase 2:

- Writes to Yahoo (no lineup setting). Scope stays `fspt-r`.
- Cron jobs, database, web push — those are Phase 3.
- Projections and salary feeds — Phase 4.
- Multi-user auth. **Decided Aug 14 2026: stay single-user and prove the flow
  against a real Yahoo account first.** Opening it up is wanted later — the
  ask was "others could be anyone" — but that needs a browser session,
  per-user token rows, and Yahoo's third-party-access clause handled (see
  [LICENSING.md](LICENSING.md)). The store is already keyed by user, so it
  stays routing, not a migration.

## Leagues

From the blueprint's Settings card:

| League | Yahoo | Key used here | Shape |
|---|---|---|---|
| Sunday Gravy | `f1/192426` | `nfl.l.192426` | 12-team, full PPR, completions count |
| The Trenches | `f1/811739` | `nfl.l.811739` | 10-team, full PPR, rush-only QBs |

`f1/<id>` is Yahoo's UI shorthand. The API wants `<game_key>.l.<league_id>`, and
the bare game code `nfl` resolves to the current season — so these keys survive
the season rollover without a code change.

## Project rules inherited from CLAUDE.md

- Real players, real news — no mocked names. That extends here: no fixture data
  standing in for a live Yahoo response outside of tests.
- Leagues have **no waivers and no player cost** (no FAAB, no bids, no
  waiver-clear times). The `transactions` endpoint exists for adds/drops and
  trades; never surface FAAB/bid fields from it.
- All timestamps render in Houston time (`America/Chicago`).
- The Trenches is a rushing league: QBs get no points from completions/passing.

## Acceptance

Phase 2 is done when, with a linked account:

1. `GET /api/leagues` returns both leagues by name.
2. `GET /api/leagues/nfl.l.192426/draft` returns every pick in order — this is
   what retires manual pick entry.
3. `GET /api/teams/<team_key>/roster` returns live rostered players with
   position, status and bye week.
4. An access token older than an hour refreshes transparently, with no
   re-authorization.
