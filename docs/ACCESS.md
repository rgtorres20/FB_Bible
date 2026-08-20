# App access: the login gate and the email allowlist

Owner request (Aug 20): a login page, and "store people I want to have
access via email." Everything shipped and tested, **off by default** —
the app stays open until you enable it, so deploying this changed
nothing by itself.

## How it works

- `/login` — the sign-in page. You sign in with your email + an owner
  code held in Vercel env. Nobody's password is ever stored; there are
  no passwords.
- `/app/access` — your access page (owner only). Add an email → the
  server mints a **one-time invite link**, shown to you exactly once
  (the server keeps only its hash). Send it however you like — text,
  email, carrier pigeon. Opening it signs that email in on that device
  for 30 days and burns the link. Unused links expire after 7 days;
  re-add the email to mint a fresh one.
- **Remove** an email and they're locked out on their very next request,
  valid cookie or not — the gate re-checks the stored allowlist every
  time.
- The allowlist lives in its own Redis key (`fbbible:auth`), outside the
  feeds blob, so no sync rebuild can ever clobber it.
- Sessions are signed cookies (HMAC over `SESSION_SECRET`); nothing
  about a session is logged, per the repo's token rule.
- The sync runner and the watchdog pass the gate with the `X-Sync-Token`
  they already hold — enabling the gate does not break the pipeline or
  the checks (`verify-live.yml` now sends it too).

## Turning it on (owner steps, Vercel → Settings → Environment Variables)

1. `SESSION_SECRET` — set a long random string if you haven't already
   (`python3 -c "import secrets; print(secrets.token_urlsafe(48))"`).
   The gate refuses to engage on the dev default.
2. `OWNER_EMAIL` — your email.
3. `APP_OWNER_CODE` — a long code only you know (generate like the
   secret above; you'll type it at /login, so a passphrase you can
   paste from a password manager is ideal).
4. `APP_AUTH` — `on`.
5. Redeploy (Vercel picks env changes up on the next deploy), then check
   `/health` → `"app_auth": "on"`. A half-set enable reports
   `"misconfigured"` and the gate deliberately **stays open** rather
   than locking you out.

Then sign in at `/login` and add people at `/app/access`.

## What is and isn't gated

Gated: everything under `/app` — the page, its data overlay, the cheat
sheet, boards, mock room, access page. Open: `/login`, `/health`, the
Yahoo OAuth endpoints, and `/api/*`. The `/api` surface carries the same
feed data the page shows; gating it would break the annotate runner's
work-list GETs, so it stays open for now — recorded as follow-up
hardening if this ever goes beyond friends
([GAP_REVIEW](GAP_REVIEW.md)).

## If you lock yourself out

Set `APP_AUTH` to `off` (or blank) in Vercel and redeploy — the gate is
env-controlled, so you can never be locked out for longer than one
redeploy.
