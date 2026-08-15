# Environments: beta and prod

How to run a beta alongside production without a second project, a second
bill, or a second copy of anything.

## The model

Vercel gives this for free: **every branch push deploys**. `main` is
production; any other branch gets its own preview deployment with its own
URL. So beta is not a second system — it is a branch.

| | Prod | Beta |
|---|---|---|
| Branch | `main` | `beta` |
| URL | `https://fb-bible-torro2.vercel.app` | `https://fb-bible-torro2-git-beta-<team>.vercel.app` (stable per branch; exact slug shown in the Vercel dashboard the first time the branch deploys) |
| `VERCEL_ENV` | `production` | `preview` |
| Badge | none | **BETA**, bottom-right (server-injected; see `app_page`) |
| CI | on every push | on every push |
| Crons (sync, verdicts, watchdog) | write here | none — see below |

`/health` reports which stage answered (`"stage": "production" | "preview" |
"local"`), so there is never a question of which deployment you are looking
at. The page itself wears a BETA badge on preview deploys for the same
reason — a beta that looks identical to prod is how wrong-tab mistakes
happen.

## The flow

```
feature branch  ->  beta  ->  main
   (preview URL      (stable beta      (production)
    per branch)       URL, CI-gated)
```

1. Work lands on a feature branch. Vercel deploys a preview; CI runs on the
   PR.
2. Merge (or push) to `beta`. That deployment is the beta: stable URL, CI
   on every push, BETA badge on screen.
3. When beta looks right, fast-forward `main` to it. That is the release.

For a solo project the `beta` hop is optional per change — small fixes can
go straight to `main`; anything touching the page, the overlay contract, or
the store should soak on beta first.

## What beta shares and what it does not

**Shared: the Upstash Redis feed store.** This is deliberate. The GitHub
Actions crons only POST to the prod URL, so beta never writes news, ADP,
Vegas or verdict data — but it reads the same store, which means beta shows
tonight's real wire with zero extra polling (and zero extra load on the
publishers; the politeness budget in `sources.py` is per-store, not
per-deploy). A beta testing *store-schema* changes must not point at the
shared store — give that branch its own free Upstash database via a
Preview-scoped `REDIS_URL` in Vercel (env vars are scoped Production /
Preview / Development; a Preview value overrides for every branch deploy).

**Not shared: writes.** `SYNC_TOKEN` is Production-scoped, so even a
misconfigured cron cannot write through a preview deploy unless you
deliberately scope a token to Preview.

**Not on beta: Yahoo login.** Yahoo matches the registered redirect URI
character-for-character, and only the prod callback is registered. The
Yahoo tab on beta shows the link button; completing the link 400s at
Yahoo. That is expected — test Yahoo flows on prod once access is granted.

**Public: both.** Vercel Deployment Protection is off project-wide because
Yahoo's OAuth redirect cannot pass a Vercel login wall. Preview URLs are
unguessable but not secret. Nothing sensitive is on the page.

## Architecture footprint (reviewed Aug 15)

Asked directly: **are we self-contained microservices? No — and that is the
right call at this scale.** This is a *modular monolith* with managed
attachments:

```
GitHub Actions (schedulers: sync / verdicts / watchdog)
      │ POST /internal/*  (shared-secret)
      ▼
FastAPI app  ── one deployable (Vercel serverless / uvicorn / Docker)
  ├── app/routes    HTTP surface (auth, league, feeds)
  ├── app/yahoo     Yahoo OAuth + JSON flattening
  ├── app/feeds     poller, parsers, ADP, Vegas, impact, render
  ├── app/store     token + feed storage behind a Protocol
  └── frontend/     the page, served same-origin with serve-time overlays
      ▼
Upstash Redis  (encrypted tokens, feed store)
```

Why not microservices: one owner, one deploy target, ~15 endpoints, and
Vercel's serverless model already gives per-request isolation and scaling.
Splitting the poller or the odds fetcher into services would add network
seams, deploy coordination and secret sprawl, and buy nothing — the crons
are *already* externalized to GitHub Actions, which is the one piece that
genuinely benefits from living outside the request path.

What keeps the monolith honest (and cheap to split later if selling ever
demands it): storage is behind the `FeedStore`/token-store Protocols, every
external feed has its own module with its own failure isolation, the
browser talks only to the HTTP surface, and nothing holds in-process state
between requests. Each `app/feeds/*` module is a service *boundary* without
the service *overhead*. The first real candidate to split in Phase 3 is the
scheduler + poller (a worker with a queue), and the store interface is the
seam it would split along.
