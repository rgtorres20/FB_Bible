# Resume here

Last worked: **Fri Aug 14 2026, ~8pm CDT.** Next session: Sat Aug 15, 11am.

## Scope check, so this file is not misread

**Yahoo is one integration, not the product.** The product is the Fantasy
Bible, and its core loop is **Alerts**: news arrives, you judge it, and it
drives roster, draft-board and target changes. Yahoo removes manual roster and
pick entry from that loop; it does not define it.

This repo currently holds only the Yahoo backend. Weighting the roadmap by
what moves the app forward, the Alerts pipeline matters more than finishing
Phase 2 — see "Alerts" below.

## One-line status

The server is **live and healthy** at <https://fb-bible-torro2.vercel.app>.
It is not yet connected to Yahoo, and that is blocked on one paste.

## The single next action

Open `.env` (gitignored, in the repo root) and paste the Upstash connection
string after `REDIS_URL=`. It starts `rediss://` — **not** the REST URL/token,
which is for a different client.

Then:

```bash
npx vercel login          # once
npx vercel link           # once, pick the fb-bible project
python scripts/push_env_to_vercel.py
```

That pushes every production variable and redeploys. `--dry-run` previews it.
Everything else in `.env` is already filled in.

## Then verify, in this order

```bash
curl https://fb-bible-torro2.vercel.app/health
```

Expect `token_store: redis` and `encryption_configured: true`. That proves
Redis is reachable and the key is valid — check it **before** the Yahoo form,
because a bad `REDIS_URL` otherwise surfaces much later as a broken login.

Then register the Yahoo app (docs/YAHOO_SETUP.md) with this exact callback:

```
https://fb-bible-torro2.vercel.app/auth/yahoo/callback
```

Yahoo matches it character for character. Add `YAHOO_CLIENT_ID` and
`YAHOO_CLIENT_SECRET` to `.env`, re-run the push script, then visit
`/auth/yahoo/login`.

Success looks like `/api/leagues` returning Sunday Gravy and The Trenches.

## Also open, not blocking

- **The app itself is still only in the Claude design project.** Paste into
  that chat: *"Commit these to the connected repo: `Fantasy Bible.dc.html` as
  `frontend/index.html`, and `data/feeds.json` as
  `frontend/data/feeds.json`."* Until then the repo is only half the project.
  Full checklist: `docs/MIGRATION.md`.
- **Sleeper attribution** is required wherever trending data shows, and the
  Alerts panel shows it today. See `docs/LICENSING.md`.
- **Confirm the production domain** in Vercel Settings → Domains. Everything
  assumes `fb-bible-torro2.vercel.app`.

## Hard-won context worth not relearning

- Vercel installs from `pyproject.toml` via `uv` and **never reads
  `requirements.txt`**. An empty `dependencies` list deploys a function with no
  packages at all, visible only as `FUNCTION_INVOCATION_FAILED`. Both
  requirements files were deleted so this cannot recur.
- **Do not add a `vercel.json`.** A `builds` key silently disables `rewrites`
  (404 everywhere) and bundles only the entrypoint. Zero-config plus
  `[tool.vercel] entrypoint` is the working setup. Details in `docs/HOSTING.md`.
- Deployment Protection must stay **off**, or Yahoo's redirect hits a Vercel
  login wall.
- Read deploy state from the GitHub commit status API
  (`/repos/rgtorres20/FB_Bible/commits/<sha>/status`), not by polling the
  endpoint — otherwise you wait on deploys that already failed. A ~2 second
  failure is config validation, not a build error.

## Health

28 Python tests, 16 JS tests, CI green on every push. `docs/` carries the spec,
licensing constraints, hosting decision and migration checklist — deliberately,
so none of it depends on chat history surviving.
