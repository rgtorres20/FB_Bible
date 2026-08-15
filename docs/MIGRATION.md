# Migration checklist — work Claude account → personal

Written 2026-08-14, while the project still spans two accounts. The goal is
that **nothing lives anywhere except this repo and services you own
personally**, so switching accounts becomes "clone the repo" rather than a
recovery operation.

## Where everything lives right now

| Artifact | Location | Personal already? | Action |
|---|---|---|---|
| Server code, tests, CI, docs | This repo | **Yes** — `rgtorres20` on GitHub | none |
| Commit authorship | `rgtorres20@icloud.com` | **Yes** — fixed in `042607a` | none |
| Local working copy | `C:\Users\rober\Projects\FB_Bible` | **Yes** — your machine | none |
| Browser API client | `frontend/lib/` | **Yes** — in repo | none |
| **`Fantasy Bible.dc.html`** | Claude design project | **No** | **must move** |
| **`data/feeds.json`** | Claude design project | **No** | **must move** |
| **Design project `CLAUDE.md`** | Claude design project | **No** | **must move** |
| Chat history / context | This session + design chat | **No** | cannot move — see below |
| Yahoo developer app | not created yet | — | create under personal |
| Vercel project | not created yet | — | create under personal |
| Upstash Redis | not created yet | — | create under personal |

The bottom four are the reason to do this **before** deploying, not after.
Anything created under a work identity has to be recreated later.

## Chat history cannot be migrated

It does not transfer between accounts, and there is no export that a fresh
Claude can usefully consume. This is by far the biggest thing that would be
"stranded."

The mitigation is already in place: every decision, constraint and gotcha has
been written into the repo rather than left in conversation.

- `CLAUDE.md` — project rules, domain rules, current state
- `docs/PHASE2_SPEC.md` — what Phase 2 is and its acceptance criteria
- `docs/LICENSING.md` — the Yahoo and Sleeper terms that constrain the code
- `docs/HOSTING.md` — the hosting decision and what it costs at Phase 3
- `docs/YAHOO_SETUP.md` — registering the Yahoo app, including the HTTPS trap
- `frontend/lib/README.md` — how to wire the page to the server

**Acceptance test for this whole migration:** a fresh Claude, given only the
cloned repo and no conversation history, can read `CLAUDE.md` and correctly
say what is built, what is blocked, and what it may not do. If that fails,
something is still stranded in chat.

## Checklist

### 1. Move the app into the repo

The design project is already connected to this repo. In that chat:

> Commit these to the connected repo: `Fantasy Bible.dc.html` as
> `frontend/index.html`, and `data/feeds.json` as `frontend/data/feeds.json`.
> Keep the contents byte-identical — this is a move, not a rewrite.

- [ ] Files committed
- [ ] `git pull` locally and confirm both are present and non-empty
- [ ] Open `frontend/index.html` in a browser — it should render as it does
      in the design preview

### 2. Copy the design project's CLAUDE.md

Its `CLAUDE.md` is *not* the same file as this repo's. It carries app state,
open items and the phase plan. Either commit it as `docs/APP_NOTES.md`, or
fold its content into this repo's `CLAUDE.md`. Do not lose it — it is the
record of every decision made in the design chat.

- [ ] Content preserved in the repo

### 3. Create third-party accounts under your personal identity

Do these **before** deploying. Each is a form, no coding.

- [ ] **Vercel** — sign in with the `rgtorres20` GitHub account, import the
      repo. Gives you `https://<project>.vercel.app`.
- [ ] **Upstash** (or any Redis) — free tier. Copy the `rediss://` URL.
- [ ] **Yahoo developer app** — register at developer.yahoo.com/apps/create
      using the Vercel URL as the callback. See `docs/YAHOO_SETUP.md`.
      **Do this after Vercel**, so the callback URL is real from the start.

### 4. Set the secrets

Secrets are deliberately **not** in git, so they are the one category that
cannot be cloned. They must be re-entered by hand wherever the app runs. Full
list — miss one and the server returns 503 or silently loses your login:

| Variable | Where it comes from |
|---|---|
| `YAHOO_CLIENT_ID` | Yahoo app |
| `YAHOO_CLIENT_SECRET` | Yahoo app |
| `YAHOO_REDIRECT_URI` | `https://<project>.vercel.app/auth/yahoo/callback` — must match Yahoo **exactly** |
| `TOKEN_ENCRYPTION_KEY` | generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `SESSION_SECRET` | any long random string |
| `TOKEN_STORE` | `redis` on Vercel — the file store loses the token between requests |
| `REDIS_URL` | Upstash |
| `CORS_ORIGINS` | wherever `frontend/index.html` is served |

- [ ] All eight set in Vercel's project environment variables
- [ ] `.env` set locally for development (it is gitignored — never commit it)
- [ ] `GET /health` on the deployed URL reports `yahoo_configured: true` and
      `encryption_configured: true`

### 5. Recreate the Claude project on the personal account

- [ ] Clone the repo on the personal account
- [ ] Run the acceptance test above — read `CLAUDE.md`, confirm the state
      description matches reality

### 6. Decommission the work account

Only after steps 1–5 pass.

- [ ] Confirm nothing in the design project is absent from the repo
- [ ] Delete or archive the design project on the work account
- [ ] Confirm no Yahoo/Vercel/Upstash account was created under the work
      identity — if one was, recreate it personally and delete the original

## Things that are easy to strand

Listed because each has bitten someone before:

- **`TOKEN_ENCRYPTION_KEY`.** Lose it and every stored token becomes
  unreadable. Not fatal — you re-link Yahoo — but confusing if unexpected.
- **The exact `YAHOO_REDIRECT_URI` string.** Yahoo matches it character for
  character, trailing slash included. A mismatch surfaces as a generic
  `invalid_request` that does not say why.
- **The design project's `CLAUDE.md`.** Easy to assume it is the same file as
  the repo's. It is not.
- **Repo visibility.** Free unlimited GitHub Actions requires a public repo.
  If you make it private for a sale, the free scheduled-job trick in
  `docs/HOSTING.md` stops being free.
