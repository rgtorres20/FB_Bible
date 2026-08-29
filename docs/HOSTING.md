# Hosting

**Decision (Aug 14 2026): stay on Vercel for now.** Free, already configured,
and the fastest route to the HTTPS callback URL Yahoo demands — which is the
only thing standing between the repo and real data before draft season.

This file records what that costs later, so Phase 3 doesn't rediscover it the
hard way.

## The limit you will hit

Verified against Vercel's docs, 2026-07-15:

| Plan | Cron jobs / project | Minimum interval | Precision |
|---|---|---|---|
| Hobby | 100 | **Once per day** | ±59 min |
| Pro | 100 | Once per minute | Per-minute |

> *"Hobby accounts are limited to cron jobs that run once per day. Cron
> expressions that would run more frequently will fail during deployment."*

The blueprint's tightest feed budget is 24h, so once-a-day technically
satisfies it. Two things it does not satisfy:

- **The app already auto-syncs the Sleeper wire when the last pull is >1h old.**
  Moving that server-side at hourly cadence needs Pro ($20/mo).
- **Injury news on a game day is an hourly concern, not a daily one.** ±59 min
  precision on a once-daily job is a poor fit for the Alerts tab.

## What that means for Phase 3

Phase 3 is "cron jobs poll the feeds on their budget intervals, write to a
database, and Settings push rules deliver via web push." On Vercel Hobby that
becomes: one daily poll, an external database, and no in-process scheduler.

When that stops being enough, the options are:

1. **Upgrade to Vercel Pro** ($20/mo) — per-minute cron, no code change.
2. **Move to a persistent container** — `Dockerfile` is already in the repo and
   kept working for exactly this reason. On Fly.io (~$5/mo) or Render (~$13/mo)
   the scheduler becomes APScheduler *inside* the FastAPI process, which needs
   no platform cron primitive at all and is portable across hosts.

Option 2 is cheaper and, if the project is ever sold, more portable — a plain
Dockerfile deploys to any buyer's infrastructure, where `vercel.json` does not.
It is deliberately not being done now.

## The external clock (owner's call, Aug 28)

GitHub's shared cron failed twice in one week: first degrading to a fifth
of the asked-for rate (measured Aug 24 — one run every 1.32h against a
15-minute cron, docs/GAP_REVIEW.md), then stalling to **zero for 32+
hours** from Aug 26 ~16:30 UTC — every scheduled workflow silent at once,
state still "active", dispatch and push events fine throughout. A commit
touching the workflow file re-registered the schedule and it resumed
about an hour later, at the same degraded cadence. During draft season
that clock does not deserve to be the only one.

**The fix: a free external cron fires `sync-feeds.yml` via
`workflow_dispatch`, so GitHub stops being the clock but stays the
runner.** Deliberately *not* a pinger hitting `/internal/sync` directly,
for two reasons:

- The workflow does two jobs: the sync call, **plus pushing the Vegas
  slate and ESPN scoreboard from the runner** (ESPN 403s Vercel's IPs).
  A direct pinger would keep the wire fresh while the odds and the Week
  review's scoreboard quietly went stale — the exact tab the owner
  already caught doing that.
- The credential is safer. A fine-grained PAT scoped to this repo with
  only Actions write can start workflow runs and nothing else; the sync
  token in a third party's hands could also *push data* (scores, odds,
  AI annotations) into the app.

Both clocks coexist: the workflow's `concurrency` group serializes
overlapping fires, and the external minutes (`3,18,33,48`) interleave
with GitHub's own (`7,22,37,52`) instead of colliding.

### Setup (once, ~10 minutes)

1. **Token** — github.com → Settings → Developer settings → Fine-grained
   personal access tokens → Generate new token. Repository access: *only*
   `rgtorres20/FB_Bible`. Permissions: **Actions → Read and write**
   (Metadata read is added automatically), nothing else. Note the expiry
   date somewhere you will see it — the job dies silently when the token
   does (the failure mode below).
2. **Cron job** — on cron-job.org (or any equivalent), one job:
   - URL: `https://api.github.com/repos/rgtorres20/FB_Bible/actions/workflows/sync-feeds.yml/dispatches`
   - Method: `POST`, body (raw JSON): `{"ref":"main"}`
   - Headers:
     `Authorization: Bearer <the PAT>` ·
     `Accept: application/vnd.github+json` ·
     `X-GitHub-Api-Version: 2022-11-28` ·
     `User-Agent: fbbible-clock` (GitHub rejects requests without one)
   - Schedule: minutes `3,18,33,48`, every hour.
   - Success is HTTP **204** with an empty body; tell the service to
     treat non-2xx as failure and email on it.
3. Optional second job, same everything, hourly at minute `45`, with
   `verdicts.yml` in the URL — covers the AI verdicts if GitHub's own
   cron stalls again. `verify-live.yml` needs no external fire; it
   watches, it does not feed.

### How this fails, so it is diagnosable

A dead external job looks exactly like the GitHub stall did — absence,
not redness. The tells, in the order to check: `sync-feeds.yml`'s run
history stops showing `workflow_dispatch` runs at `:03/:18/:33/:48`; the
cron service's own dashboard shows 401 (token expired or revoked — issue
a new one, update the job) or 404 (token lost repo access). Data health
keeps reporting honestly through any of it, and the 24h feed budgets
mean nothing on screen lies before someone notices.

## Vercel deployment notes

**There is no `vercel.json`, and that is deliberate.** Vercel's Python runtime
detects FastAPI and routes every request to the app. `pyproject.toml` names
the entrypoint:

```toml
[tool.vercel]
entrypoint = "app.main:app"
```

Same app object as uvicorn and Docker — nothing Vercel-specific in the code.

### Dependencies live in `pyproject.toml`, not `requirements.txt`

**Vercel installs with `uv` from `pyproject.toml` and does not fall back to
`requirements.txt`.** An empty `[project] dependencies` list therefore deployed
a function with *no dependencies installed at all* — every import failed and
the only symptom was `FUNCTION_INVOCATION_FAILED`.

Both requirements files were deleted so this cannot drift again. Extras split
the difference between environments:

- base — what the function needs
- `[server]` — adds uvicorn, for Docker and local dev only; Vercel brings its
  own ASGI server, so it stays out of the bundle
- `[dev]` — pytest, respx, ruff

The bundle listing that revealed this (`uv.lock`, `.python-version`,
`_vendor/`, none of them committed) is worth remembering: it tells you which
installer ran and where packages landed.

### Do not reintroduce a `builds` key

The first attempt used the legacy `builds` config and burned three deploys.
None of these failures name themselves in the response, so they are recorded
here.

1. **`builds` silently disables `rewrites`.** With a `builds` key present
   Vercel uses legacy routing and ignores `rewrites` entirely. Symptom: every
   path returns `404 NOT_FOUND` including `/health`, while the function is
   deployed and reachable at its literal source path (`/api/index.py`).
2. **`builds` bundles only the entrypoint.** The sibling `app/` package was
   absent at runtime, so `import app` failed. Symptom: `500
   FUNCTION_INVOCATION_FAILED`, no detail in the body. `includeFiles` is the
   documented patch — but it is only needed *because* of `builds`. Zero-config
   "includes all files from your project that are reachable at build time."
3. **`vercel.json` rejects pseudo-comment keys.** Adding `"// note": "..."`
   entries fails schema validation and the deployment is rejected before it
   builds. The commit status links to generic configuration docs without
   naming the offending key.

The lesson worth keeping: with `builds`, each fix exposed the next failure.
Zero-config removes all three at once.

### Reading deploy failures without dashboard access

Vercel's response bodies carry no diagnostic detail and the real errors are in
the dashboard's build and runtime logs. Two things that helped:

- The GitHub commit status API reports per-commit deploy state:
  `/repos/<owner>/<repo>/commits/<sha>/status`. Poll that alongside the
  endpoint, otherwise you can spend a long time waiting on a deploy that
  already failed.
- A deploy that fails in ~2 seconds failed *validation*, not the build.

Deployment Protection also has to be off (Settings → Deployment Protection →
Vercel Authentication → Require Log In). While it is on, Vercel's standard
protection covers generated `.vercel.app` production URLs, every request 302s
to `vercel.com/sso-api`, and OAuth cannot complete: Yahoo's redirect and the
browser app's `fetch` calls both hit the login wall. The API's real protection
is the OAuth token — every endpoint returns 401 without a linked account.
- **`TOKEN_STORE=redis` and `REDIS_URL` are required.** Serverless has no
  writable disk; the file store will silently lose the token between
  invocations. Upstash has a usable free tier.
- Set `YAHOO_CLIENT_ID`, `YAHOO_CLIENT_SECRET`, `YAHOO_REDIRECT_URI`,
  `TOKEN_ENCRYPTION_KEY` and `SESSION_SECRET` as project environment variables.
- `YAHOO_REDIRECT_URI` must be `https://<project>.vercel.app/auth/yahoo/callback`
  and must match the Yahoo app registration **exactly**.
- Set `CORS_ORIGINS` to wherever `Fantasy Bible.dc.html` is served.

## Yahoo's 24-hour retention rule

Independent of host: Yahoo user data must be removed within 24h of being
obtained (see [LICENSING.md](LICENSING.md)). On Redis that is a TTL. Anything
cached browser-side is covered by the client module's hard expiry — see
[../frontend/lib/README.md](../frontend/lib/README.md).
