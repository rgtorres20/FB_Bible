# Phase 4 — Productize

**Status: planning only.** Nothing here is licensed to be built yet; this
file exists so the cost, the blockers and — most importantly — the
*order* are written down while they are fresh. The repo is still Phase 2
(see CLAUDE.md); Phase 3 is cron/database/push.

"Productize" here means one specific transition: from **the owner plus
five testers, free, personal use** to **something other people pay for.**
Most of the work is not code.

## What a domain actually buys

Asked directly, Aug 21. Grouped by *when* it matters, because two of
these get more expensive the longer they wait.

**Matters right now — and the cost of delay is other people's data:**

1. **Every user's browser-side state survives.** This is the big one and
   it is bigger than passkeys. Fifteen `localStorage` keys are bound to
   the origin, and a domain move wipes all of them for everyone:
   `ww_my_teams` (the drafted roster, per league), `ww_taken` (players
   marked gone mid-draft), `ww_queue`, `ww_my_sleepers`,
   `ww_scout_dismissed`, `ww_cuff_order` / `ww_cuff_hidden` (a
   customized layout), `ww_src_w` / `ww_src_weight` (source weighting),
   `ww_theme` / `ww_skin`, `fb_visit` (what the NEW badges compare
   against). `/app/mine` is server-side and survives a move; none of
   this does. Losing it mid-season, mid-draft-prep, is a real loss.
2. **Passkeys survive.** Credentials are hostname-bound, so every Face ID
   registration dies on a move.
3. **You stop being a tenant of your own URL.** Today the address *is*
   the host. Moving off Vercel for any reason — the non-commercial
   clause, pricing, an outage, a better fit — breaks every bookmark,
   home-screen install, passkey and localStorage blob at once. With your
   own domain you repoint DNS and nobody notices anything happened.

**Matters once other people use it:**

4. **Invite mail that lands in inboxes.** SPF/DKIM/DMARC on a domain you
   control is what separates "invite" from "spam folder" as volume grows.
5. **It reads as a product.** `fb-bible-torro2.vercel.app` looks like a
   dev preview — including the random suffix, which means the clean name
   was already taken.
6. **Real addresses.** Cloudflare Email Routing forwards `you@yourdomain`
   free on domains registered there.
7. **Clean stages.** `app.` and `beta.` subdomains instead of two
   unrelated Vercel URLs (see ENVIRONMENTS.md).

**Matters only if selling:**

8. Digital Asset Links for a Play Store TWA listing.
9. Stripe, terms and privacy policy all assume a stable domain.

One honest counterpoint: `.vercel.app` is on the Public Suffix List, so
cookies cannot be shared across it — that is *protective* today. On your
own domain you control subdomain cookie scope yourself, which is more
power and more rope.

## What it costs

Today the whole system runs at **$0/month** (public repo → unmetered
GitHub Actions; Vercel Hobby; Upstash free tier; Google AI free tier;
Gmail SMTP). Here is what each step off that actually adds:

| Item | Cost | When it becomes required |
|---|---|---|
| **Domain, `.com`** | **~$10.44/yr** at Cloudflare (at-cost, same price at renewal) | Any time — cosmetic until you sell |
| Domain, `.app` | ~$12–20/yr | Alternative; forces HTTPS, which we already do |
| Domain, `.io` | ~$35–60/yr renewal | Not worth it here |
| **Vercel Pro** | **$20/mo** | The moment you charge anyone — Hobby is licensed **non-commercial** |
| Upstash paid | ~$0 until ~500K commands/mo, then cents per 100K | Somewhere past a few dozen active users |
| Transactional email | $0 → ~$15/mo (Postmark/Resend) at volume | When Gmail SMTP starts landing invites in spam (see below) |
| Google AI paid tier | $0 today | Only if the free tier's limits stop fitting |
| Google Play account | **$25 one-time** | Only if shipping an Android store listing |
| Apple Developer Program | **$99/yr** | Only if shipping an iOS store listing |
| **Floor to sell (web)** | **~$21/month** (Vercel Pro + domain amortized) | — |

Beware the first-year-promo trap: registrars advertise $1–6 first years
and renew at $15–25. Cloudflare's at-cost model has no promo *and* no
renewal jump, which is why it's the recommendation.

## Is the current setup legal?

Short answer: **yes, what is running today is fine** — and the reasons
are worth writing down, because they are exactly the reasons that stop
being true when money enters.

What makes today's use defensible:

- **It is not commercial.** Nobody pays. Yahoo's and Sleeper's terms both
  gate *selling*, not personal use.
- **It is small and private.** Six people behind a login gate is not
  publication or distribution.
- **The feeds are consumed the way feeds are meant to be.** Headlines,
  timestamps, and links back to the source — never republished article
  bodies. Sleeper attribution is displayed as their terms require.
- **Per-user data isolation exists** (`/app/mine`, per-email keys), which
  LICENSING.md lists as a prerequisite for anyone but the owner using it.

The one genuine exposure even now, stated plainly: **the Titans-mode
watermark is the club's real trademark.** At six private users, free,
behind a sign-in, the practical risk is about as close to zero as these
things get — trademark claims turn on use *in commerce* and likelihood of
confusion, and none of that is present. But it is a real mark, it is in
the repo, and it must be swapped for an original emblem before anything
ships publicly or for money. That is already on the list below.

Everything else that changes is on someone else's clock (Yahoo's
permission, Sleeper's licence), which is the argument for starting the
paperwork early rather than when the code is ready.

*This is an engineering read of published terms, not legal advice. Before
actually charging anyone, a lawyer should look at the Yahoo and Sleeper
agreements and whatever terms/privacy policy ships with the product.*

## Blocking, and not code

From [LICENSING.md](LICENSING.md) — these gate *selling*, not building:

1. **Yahoo**: prior written permission required to sell anything built on
   their Fantasy API. Also their 24-hour deletion rule for Yahoo-sourced
   user data becomes a real purge job the moment a database exists.
   (Yahoo API access itself is still pending approval — a prerequisite to
   the prerequisite.)
2. **Sleeper**: a commercial licence for trending data. Attribution is
   already displayed and that part is satisfied.
3. **NFL / club marks**: the Titans-mode watermark is currently the
   club's real sword mark, at the owner's request, for personal use. It
   **must** swap back to an original emblem before distribution — the
   stand-in is one commit away in git history.
4. **Terms + privacy policy**: needed once strangers hold accounts, and
   doubly so given Yahoo data is involved.

## Technical gaps that only bite with real users

Already tracked in [GAP_REVIEW.md](GAP_REVIEW.md); listed here because
they are the ones that change from "fine" to "not fine" at the moment
money changes hands:

- **`/api/*` is ungated** (#11). Fine for friends; move the annotate
  runner's work-list GETs behind `X-Sync-Token` and close it.
- **No Redis backup** (#10). A flush today loses the 21-day archive and
  every AI surface. Paying users make that an outage, not an annoyance.
- **Store writes race** (#8). Whole-blob load-modify-save with no
  locking; more concurrent users makes the window matter.
- **Invite email deliverability.** Gmail SMTP is fine for six people and
  will start hitting spam folders as volume grows — a real transactional
  sender (SPF/DKIM on the custom domain) is the fix, and it wants the
  domain to exist first.
- **Per-user data isolation** is done (`/app/mine`, per-email keys), which
  was itself on LICENSING's "before anyone else uses it" list.

## Mobile: do the app stores actually help?

Worth separating two things people conflate — **an app icon on a phone**
and **a store listing**. The first is already done and free; only the
second costs anything.

**What already works, today, for $0:** the app is a PWA (manifest +
service worker). On iPhone, Safari → Share → *Add to Home Screen* gives a
real icon, full-screen chrome-free launch, and offline caching. On
Android, Chrome offers the same install prompt. For the owner and five
testers this is genuinely the whole answer — no store, no review, no fee.

A store listing buys exactly two things beyond that: **discovery by
strangers** and **the store's payment rails**. Neither matters until
selling.

**Google Play — easy.** Google supports PWAs directly via *Trusted Web
Activity*: package with Bubblewrap or PWABuilder, host a Digital Asset
Links file on the domain to prove ownership, meet a Lighthouse PWA score
of ~80. Cost is the **$25 one-time** developer fee. Realistically a day
or two of work, not a project. (Agencies quote $3–6K for this; that is
the price of someone else running a packaging command.) Note the
dependency: **it needs the custom domain first** — another reason the
domain is step one.

**Apple — hard, and possibly not worth it.** Guideline **4.2 (Minimum
Functionality)** and **4.2.2** explicitly reject "repackaged websites"
and "web clippings." A WebView wrapper around this app gets rejected.
Passing review means building genuinely native functionality — push
notifications, offline draft board, widgets, native navigation — which is
a real iOS project, not a wrapper. Cost is **$99/yr** plus that build.

**The payment question, which is the actual decision.** Sell through a
store and the store takes a cut: Apple and Google both 15% under $1M/yr,
30% above. Sell through the *web* — Stripe on the custom domain, users
sign in to the PWA — and there is **no store cut at all**. Apple's
anti-steering rules were struck down in the US (Epic injunction, April
2025) so external purchase links are now permitted; Apple is litigating
for a 5–15% linkout fee and the rate is still unresolved as of Aug 2026.
The stable conclusion regardless of how that lands: **web-first selling
avoids the whole question.**

**Two extra frictions specific to this app:**

- *Fantasy sports scrutiny.* Store policies police contests with entry
  fees and prizes. This is draft prep — no money, no contests — so it
  should not apply, but the category can draw extra review attention.
- *Yahoo compounds.* A paid store app on Yahoo's API needs their written
  permission unambiguously, and the 24-hour deletion rule gets harder to
  honor with a mobile client caching data.

**Recommended posture:** PWA install for everyone now → if selling, sell
on the web with Stripe → Google Play via TWA as cheap extra distribution
→ treat iOS App Store as a separate, later, genuinely-native decision.

## The order — and the one trap

The sequence matters more than the list, because two items create rework
if done late:

1. **Buy the domain and point it at Vercel *first*.**
   **Passkeys are bound to the hostname.** Every Face ID / Touch ID
   credential registered against `fb-bible-torro2.vercel.app` silently
   stops being offered when the app moves to `fantasybible.com` —
   everyone re-registers. Cheap now, annoying after five testers, bad
   after fifty users. This is the single strongest argument for spending
   the $10 early even though nothing else requires it.
   (Cloudflare Registrar requires its own nameservers; that is fine —
   host the DNS there and point records at Vercel in DNS-only mode.)
2. **Then** set up the real email sender on that domain (SPF/DKIM).
3. **Then** close `/api/*` and add the Redis backup job.
4. **Then** the legal track — Yahoo permission, Sleeper licence, mark
   swap, terms/privacy — which runs on someone else's clock and should
   start as early as possible.
5. **Only then** Vercel Pro + Stripe on the web, which is the cheap, fast
   part — and which sidesteps store commissions entirely.
6. **Optional, after all that:** Google Play via TWA ($25, needs the
   domain from step 1). iOS is its own decision, not a packaging step.

## Open decisions

- What is actually sold: a hosted subscription, or a self-host others
  deploy with their own keys? The second sidesteps most of the Yahoo
  data-handling burden and is worth considering seriously.
- Whether the design document (`frontend/index.html`, a Claude Design
  export) is redistributable as-is under the product.
