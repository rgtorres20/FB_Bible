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

## Vercel deployment notes

- `vercel.json` routes everything to `api/index.py`, which re-exports
  `app.main:app`. Same app object as uvicorn and Docker.

### Three ways this config broke, so nobody rediscovers them

`vercel.json` cannot carry comments, so they live here. All three were hit on
the first real deploy, and none of them announce themselves clearly.

1. **`routes`, not `rewrites`.** When a `builds` key is present, Vercel uses
   legacy routing and *silently ignores* `rewrites`. Symptom: every path
   returns `404 NOT_FOUND`, including `/health`, while the function itself is
   deployed and reachable at its literal source path.
2. **`includeFiles: app/**` is required.** With an explicit `builds` entry only
   the entrypoint is bundled, so the sibling `app/` package is absent at
   runtime and `import app` fails. Symptom: `500 FUNCTION_INVOCATION_FAILED`
   with no detail in the response body. `api/index.py` also inserts the repo
   root on `sys.path` so the import cannot depend on the runtime's working
   directory.
3. **No pseudo-comment keys.** Adding `"// note": "..."` entries — a common
   trick in other tools' JSON configs — fails Vercel's schema validation and
   the whole deployment is rejected before it builds. The commit status links
   to the project-configuration docs rather than naming the offending key.

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
