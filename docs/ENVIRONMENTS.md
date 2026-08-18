# Environments: beta and prod

Two deployments of one codebase, at no extra cost.

## The model

This doc originally described beta as a branch preview under a single
Vercel project. **That is not how it is actually set up** (found 2026-08-18
by pointing the watchdog at it): preprod is its own Vercel project serving
`fb-bible.vercel.app`, alongside the `fb-bible-torro2` project that serves
production. Both build from this repo, both read the same Upstash store.

The distinction that matters is not project-vs-branch, it is that a second
project's own deploy calls itself `production` — so the stage has to be
declared explicitly rather than inferred. Hence `FB_STAGE` below.

| | Prod | Beta |
|---|---|---|
| Branch | `main` | `beta` |
| URL | `https://fb-bible-torro2.vercel.app` | `https://fb-bible.vercel.app` (verified live 2026-08-18: 35/35 checks pass, same Redis, same data) |
| `VERCEL_ENV` | `production` | `production` — see below |
| `FB_STAGE` | unset | optional — the branch fallback covers it |
| Stage resolved from | `VERCEL_ENV` | branch is `beta` → `preview` |
| Badge | none | **BETA**, bottom-right (server-injected; see `app_page`) |
| CI | on every push | on every push |
| Crons (sync, verdicts, watchdog) | write here | none — see below |

`/health` reports which stage answered (`"stage": "production" | "preview" |
"local"`), so there is never a question of which deployment you are looking
at.

**The preprod deployment is a separate Vercel project, not a branch
preview**, which breaks the obvious assumption: Vercel labels a project's
own production deploy `production` regardless of which branch feeds it. So
`fb-bible.vercel.app` reported `stage: production` and rendered **no BETA
badge** — a preprod pixel-identical to the real thing, which is precisely
the wrong-tab hazard the badge exists to prevent.

### How the stage is decided (Aug 18)

`Settings.stage` resolves in this order:

1. **`FB_STAGE`** if set — an explicit answer always wins, in either
   direction.
2. **The git branch**, via `VERCEL_GIT_COMMIT_REF`. Anything in
   `PREVIEW_BRANCHES` (today: `beta`) is a preview no matter what the host
   calls the deploy. Prod builds from `main` and is unaffected.
3. **`VERCEL_ENV`**, then `"local"`.

Step 2 is why no dashboard setting is required: preprod builds from `beta`,
and a deploy already knows the branch it came from. The original fix here
was "set `FB_STAGE=preview` on that project", which worked but depended on
a human remembering a setting that nothing checks.

**The one way step 2 goes quiet:** a Vercel project with *Automatically
expose System Environment Variables* turned off hands the function no ref,
so the fallback sees an empty string and does nothing. `/health` now
reports `"branch"` for exactly this reason — an empty value there is the
diagnosis, and the fix is either flipping that toggle (Settings →
Environments) or setting `FB_STAGE=preview` by hand after all.

Dashboard note: on the current Vercel UI the variables live under
**Settings → Environments → Production** for the `fb-bible` project —
Production, not Preview, because that project's own deploys report as
production. There is no separate "Environment Variables" sidebar item.

## The flow

```
feature branch  ->  beta branch          ->  main
   (branch preview    (fb-bible.vercel.app     (fb-bible-torro2
    under either       -- its own project,      .vercel.app)
    project)           CI-gated)
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

**Writes: not verified, do not assume.** The original claim here was that
`SYNC_TOKEN` is Production-scoped so a preview cannot write. That reasoning
assumed a branch preview under one project, and preprod is a separate
project with its own fully-provisioned environment — it already has Redis
and the encryption key. Whether it also carries `SYNC_TOKEN` has not been
checked. In practice nothing writes through it, because all three crons
POST to the production URL by name. Treat "preprod cannot write" as
unverified until someone looks at that project's environment variables.

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
