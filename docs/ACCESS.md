# App access: the login gate and the email allowlist

Owner request (Aug 20): a login page, and "store people I want to have
access via email." Everything shipped and tested, **off by default** —
the app stays open until you enable it, so deploying this changed
nothing by itself.

## How it works

- `/login` — the sign-in page. **One form for everyone**: your email,
  and either the owner code held in Vercel env (yours) or the password
  the person chose from their invite (everyone else's).
- **Passwords, since Aug 24.** The allowlist says *who is allowed*; a
  credential says *how they prove it is them*. An invite link proves it
  once and a passkey proves it on one device, so neither answers "they
  should have access on any device until I remove them" — a password
  does. Stored as `hashlib.scrypt` (stdlib, memory-hard, ~50ms a check)
  with a per-user salt, inside the person's allowlist entry so removing
  them takes the credential with it. The owner's credential stays the
  env-held code, so a leaked store never contains the owner's way in.
- **The sign-in door is throttled** — five wrong tries against one
  address locks *that address* for fifteen minutes, counted per email
  because an attacker picks their IP and cannot pick whose account they
  want. The lock is short and self-clearing on purpose: otherwise
  hammering someone's address would be a way to keep them out.
- **The reset is a fresh invite.** There is no email-based reset because
  there is no reliable outbound email yet; minting a new link is the
  recovery, and it is rare rather than monthly.
- `/app/access` — your access page (owner only). Add an email → the
  server mints a **one-time invite link**, shown to you exactly once
  (the server keeps only its hash, so it can never be shown again).
  Send it however you like — text, email, carrier pigeon. Opening it
  shows a **confirm page**; the button on that page is what signs them
  in, for 30 days on that device, and burns the link. Unused links
  expire after 7 days.
- **Opening a link does not spend it — clicking the button does.** Mail
  clients and chat apps fetch links to build previews, and corporate
  mail scanners open every link to check it, all of them with a GET. A
  one-time link that accepted on GET could be burned before the invitee
  ever touched it, and they would arrive at "already used" with no way
  to know why. It is also simply what HTTP says a GET is for.
- **One link, one device.** The session is a cookie, so it lives in the
  browser that accepted it. Someone who wants the app on a phone *and*
  a laptop needs a link for each — mint the second with **New link**.
  The way to stop that recurring is a passkey: once they are in on a
  device, `/app/mine` → "Set up on this device" makes their face or
  fingerprint the sign-in there, and they never need you again on it.
- **Lost the link before you copied it?** Every unused invite has a
  **New link** button beside it. It mints a replacement in one click —
  no retyping the address — and **supersedes the old one**, so use it
  when a link was lost, not after you have sent it.
- **One live link per person, always.** Minting used to be purely
  additive: re-adding an email three times left three working links,
  every one a live way in and only the newest known to you. Since Aug 22
  a fresh invite drops the unused one for that address (and only that
  address — everyone else's pending link is untouched). This is what
  makes the New link button safe to offer.
- **Remove** an email and they're locked out on their very next request,
  valid cookie or not — the gate re-checks the stored allowlist every
  time.
- The allowlist lives in its own Redis key (`fbbible:auth`), outside the
  feeds blob, so no sync rebuild can ever clobber it.
- **That key is encrypted at rest** (Aug 24), with the same
  `TOKEN_ENCRYPTION_KEY` the Yahoo tokens use. Before passwords the blob
  held addresses and passkey *public* keys — nothing that impersonates
  anyone if it leaked. Password hashes changed that, so the blob is now
  sealed as well as hashed.
- **So is each person's own layer** (`fbbible:user:{email}` — the
  documents, ranking lists and league settings they typed at `/app/mine`
  and `/app/leagues`). It holds no credential, so it is a smaller prize
  than the access list, but it is somebody's own writing rather than a
  headline the app polled. "Not Yahoo data" is a *retention* rule
  (docs/LICENSING.md), not a reason to leave it legible in a dump.

  See **Key rotation** below: it is the one operational consequence of
  both.
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

**First run, in order:** set the four vars → redeploy → check `/health`
shows `"app_auth": "on"` → sign in at `/login` with your email and owner
code → open `/app/mine` and hit "Set up on this device" so Face ID works
from then on → add your testers at `/app/access`.

## Passkeys — Face ID / Touch ID

Once you (or anyone you've invited) has signed in once the normal way,
`/app/mine` offers **"Set up on this device"**. After that the login page
shows **Sign in with Face ID / Touch ID** and a face or fingerprint is the
whole sign-in — no email typed, no code, no link.

How it behaves, deliberately:

- A passkey is a faster way in for someone who **already** has access,
  never a way to grant it. Registration needs a live session; sign-in
  still ends at the same allowlist check.
- Remove someone from the allowlist and their passkeys are deleted with
  them — the key on their phone stops opening anything immediately.
- Only public keys are stored. The private half never leaves the
  device's secure enclave, so this app holds nothing that could
  impersonate anyone even if the store leaked.
- Passkeys are bound to the site's hostname. **Moving to a custom domain
  means everyone re-registers** — the old keys silently stop being
  offered. Worth doing the domain move before handing out invites.
- Works on iPhone/iPad/Mac (Face ID, Touch ID), Android, and Windows
  Hello. The button only appears where the browser supports it; the
  owner code and invite links keep working everywhere as the fallback.

### Pinning the RP ID before you move again

A passkey is scoped to an **RP ID**, which defaults to the hostname. That
makes `fantasysportsbible.com` and `app.fantasysportsbible.com` two
different relying parties: every credential registered under one is dead
under the other. Moving between them is a re-registration for everybody,
and doing this afterwards does not un-break them.

Set **`PASSKEY_RP_ID=fantasysportsbible.com`** in Vercel env and a
credential registered at the apex keeps working on any subdomain you add
later. Leave it blank and behaviour is exactly what shipped.

It is a setting rather than something derived because working out "the
registrable domain" from a hostname needs the Public Suffix List — a
naive last-two-labels is wrong for `.co.uk` and a hundred others, and
being wrong makes WebAuthn refuse every registration. A value the host
does not actually sit under is ignored and the hostname is used instead,
so a typo degrades to the old behaviour rather than breaking sign-in.

The origin is never widened, only the RP ID — it still has to match the
browser exactly.

## Emailing invites automatically (optional)

Adding an email can also send the invite for you — the message carries
the one-time link, how to set a password, and a short intro to the app
(`app/mailer.py` is the template).

It deliberately carries **no league links** (owner, Aug 25: *"those are
my personal teams"*). The Yahoo URLs being public routing is beside the
point: email is the one surface that leaves the gate, so a forwarded
invite, a shared inbox or a mail archive puts your teams in front of
people who were never given access. Inside the app the allowlist decides
who sees them; an email decides nothing. A test pins their absence.

> **SMTP does not work on Vercel.** Learned the hard way, Aug 21: the
> serverless sandbox hangs outbound SMTP connections, so a completely
> correct iCloud or Gmail configuration still times out in production.
> No port, password or provider fixes it there. Mail has to go over
> HTTPS instead. SMTP remains supported and is the simplest option for
> local or self-hosted runs, where it works fine.

**The transport that works on Vercel — Resend over HTTPS:**

1. Sign up at resend.com (free tier: 3,000 emails/month) and create an
   API key.
2. Vercel env: `RESEND_API_KEY=re_...`
3. **To email anyone but yourself, verify a domain** at
   resend.com/domains and set `MAIL_FROM=invites@yourdomain`. Until
   then the default sender (`onboarding@resend.dev`) can only reach the
   address on your own Resend account — enough to prove the pipe works,
   not enough to invite testers. This is the real reason the custom
   domain sits at step 1 of docs/PRODUCTIZE.md.

**SMTP, for local and self-hosted runs.** Gmail: an app password from
Google Account → Security → 2-Step Verification → App passwords, then
`SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER`, `SMTP_PASS`.
iCloud: `SMTP_HOST=smtp.mail.me.com`, `SMTP_PORT=587`, your full iCloud
address, and an **app-specific password** from appleid.apple.com →
Sign-In and Security. The normal Apple password will not authenticate,
and iCloud supports only 587/STARTTLS, never 465.

Unset, the access page simply shows you the link to send yourself; a
failed send falls back to the same, honestly labelled. Nothing about a
link is ever logged either way.

**Checking it works:** `/health` reports `invite_email` as the actual
transport — `"http"`, `"smtp"` or `"off"` — so "smtp" on a Vercel
deploy is visibly the doomed combination rather than a mystery. The
watchdog prints it and says so. `/app/access` has a **Send myself a
test** button that reports the real reason on failure: an app-password
problem, an unverified Resend domain, and a sandbox that blocks the
socket all need different fixes and now say which one happened.

## Each user's own data — /app/mine ("My stuff")

The base app is shared; `/app/mine` is each signed-in person's own
layer: up to 12 named documents (notes, target lists, rankings, pasted
or uploaded text/CSV, 200KB each), stored under their email's own Redis
key (`fbbible:user:{email}`) and shown to nobody else — the owner has
no browse-others view, deliberately. Not Yahoo-sourced data, so the
24-hour deletion rule does not apply. Real file/blob uploads (PDFs,
images) would need Vercel Blob — a Phase 3 decision.

## What is and isn't gated

Gated: everything under `/app` — the page, its data overlay, the cheat
sheet, boards, mock room, access page. Open: `/login`, `/health`, the
Yahoo OAuth endpoints, and `/api/*`. The `/api` surface carries the same
feed data the page shows; gating it would break the annotate runner's
work-list GETs, so it stays open for now — recorded as follow-up
hardening if this ever goes beyond friends
([GAP_REVIEW](GAP_REVIEW.md)).

## Key rotation, and what a lost key looks like

`TOKEN_ENCRYPTION_KEY` now opens three things: the Yahoo tokens, the
access list, and every user's own documents. Change it and all three stop
opening — the difference is that a lost Yahoo token is re-earned by
signing in to Yahoo again, while a lost access list is everyone you
invited and a lost personal layer is what they wrote by hand.

What the app does about that is the part worth knowing:

- A blob it cannot decrypt **raises** rather than reading as empty. That
  distinction is the whole safeguard. Every action on both blobs is
  read → change → write, so one that read as "empty" would be
  *overwritten* with whatever you did next, and the real data would be
  gone for good rather than merely locked. Concretely: adding one user
  would replace the whole allowlist, and saving one league setting would
  replace that person's documents and ranking lists.
- So a wrong key is **recoverable**: put the old value back and
  everything returns. Nothing was deleted.
- While the key is wrong, `/app/*` answers **503** naming
  `TOKEN_ENCRYPTION_KEY` rather than a bare 500 — and it says *which*
  blob would not open, "access list" or "personal documents", so you are
  not guessing. The gate stays shut for everyone but you (the owner
  passes on the env check alone).
- `/health` reports `"stored_data_at_rest"`, covering both blobs since
  one key governs them. `"encrypted"` is correct; `"plaintext"` means no
  key is set and both are being written in the clear — which is what
  local dev does, and what production must not. `verify-live.yml` fails
  on it.

**To rotate deliberately** you would need to decrypt with the old key and
re-encrypt with the new one; there is no built-in re-key command, because
with a handful of users the honest answer is to set the new key and
re-invite. If the user count ever makes that silly, that is the point to
write the migration.

A blob written **before** Aug 24 is plaintext JSON and still opens
normally — it is re-sealed by the next write (any add, removal, password
set, saved document or league edit). Nobody was locked out of their own
data to gain this.

## If you lock yourself out

Set `APP_AUTH` to `off` (or blank) in Vercel and redeploy — the gate is
env-controlled, so you can never be locked out for longer than one
redeploy.

## What the gate deliberately does not cover

`/app/*` is gated, with a **tight allowlist of four public paths**:

    /app/assets/…            the brand mark and favicon
    /app/icons/…             the home-screen icons
    /app/teams.css           the club colour tokens
    /app/manifest.webmanifest

These carry brand art and colour values and no user data of any kind.
They are public because **the sign-in page is public and references
them** — without this, `/login` rendered while its logo, its favicon and
its theme all returned 401, so the page looked broken to exactly the
people it exists for. Anyone not signed in yet.

That bug survived the watchdog for a day: every check sends the sync
token and therefore walks through the gate, so they proved the files
*existed* while a signed-out visitor could not fetch them. `verify-live`
now checks these four **anonymously**, and separately asserts the
allowlist opened nothing else.

`/api/*` also stays outside the gate, for a different reason (the
annotate runner's work-list GETs) — recorded as GAP_REVIEW #11.
