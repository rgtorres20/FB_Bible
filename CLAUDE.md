# FB Bible server — project rules

The backend half of the Fantasy Bible. The browser app (`Fantasy Bible.dc.html`)
lives in the Claude design project; this repo is **Phase 2 only** — the Yahoo
league link. Read [docs/PHASE2_SPEC.md](docs/PHASE2_SPEC.md) before changing
scope.

## Inherited domain rules

These come from the app's own CLAUDE.md and still bind here:

- Team watcher + fantasy draft tool for the **2026 NFL season**. Real players,
  real news — no mocked names, and no fixture data standing in for a live Yahoo
  response outside of `tests/`.
- The user's leagues have **no waivers and no player cost** — no FAAB, no bids,
  no waiver-clear times. Adds are free, first-come. Never surface FAAB/bid
  fields from the transactions endpoint. (Verified against the real Yahoo
  settings, Aug 19.)
- Leagues — corrected Aug 19 from the owner's actual Yahoo settings pages,
  which override every earlier chat-era description
  ([docs/LEAGUES.md](docs/LEAGUES.md) is the ground truth):
  **NDDPL** `nfl.l.192426` (10-team) and **RED_EYE** `nfl.l.811739`
  (**12-team** — owner correction Aug 20, superseding the PDF's 10),
  **both full PPR, both IDP** (8 defensive starters each); plus
  **BALLAPALOSA** `963878` (10-team, settings page Aug 21) — full PPR,
  **team D/ST instead of IDP**, and receiving yardage *not* halved.
  A league starts individual defenders or a team defense, never both.
- **QBs score above market in both leagues** — 6-pt passing TDs and
  20 pass yds/pt in both; RED_EYE adds **1 pt per completion**. The old
  "rushing league, QBs score nothing for passing" rule had it backwards
  and is dead. Rank QBs per league, in the premium direction.
- Receiving yardage is **halved** (20 yds/pt) in both leagues while
  receptions stay 1.0 — weigh targets over air yards.
- All timestamps render in the user's Houston timezone (`America/Chicago`).
- Trusted news sources: NBC Sports, @AdamSchefter, Rotowire, ESPN, CBS,
  Yahoo's wire.

## The mark

The app's identity — open book as a football field, gold trophy, FSB —
ships as vector in `frontend/assets/` and is wired into every served page
through `skin.FAVICON`. Rules that bind code: the wordmark is white and
gold, so **it always sits on its own navy panel** (it disappears on the
light theme otherwise), and the two manifest PNGs are *rendered from* the
icon SVG, so they get regenerated whenever it changes.
[docs/BRAND.md](docs/BRAND.md) has the palette and the swap procedure for
dropping in different artwork.

The app wears **one of 32 club themes, Dark, or Light**, and opens on the
club theme (the house navy until someone picks a club). The palettes are
*generated* from each club's two published marks in `app/feeds/teams.py`
and served as `/app/teams.css`; the generator guarantees the contrast
rather than assuming it, and the tests assert it for all 33. `ww_theme`
and `fb_team` are immutable storage keys, and the retired `cowboys` /
`titans` values are translated, never reset.

## Commercial posture

This may be sold. That reverses the app's original "doesn't care about
licensing constraints" note — see [docs/LICENSING.md](docs/LICENSING.md) for
the verified terms. Two consequences bind code, not just paperwork:

- **Yahoo user data must be deleted within 24h of being obtained.** When Phase
  3 adds a database, Yahoo-sourced rows need a TTL and a purge job. Non-Yahoo
  feeds are unaffected.
- **Sleeper requires attribution for trending data,** which the Alerts panel
  already displays. That applies now, not just commercially.

Selling requires prior written permission from Yahoo and a commercial licence
from Sleeper. Neither blocks personal single-user use.

## Rules for this repo

- **Read-only against Yahoo.** Scope stays `fspt-r`. If a change needs
  `fspt-w`, that's a scope decision, not an implementation detail — ask first.
- **Never log or return a token.** Not the access token, not the refresh token,
  not in an error message. `/auth/yahoo/status` returns expiry metadata only.
- **Tokens go through `app/store`.** Don't read or write `.tokens.json` or
  Redis directly, and don't add a store that skips `TokenCipher`.
- **Keep both run targets working.** Any change has to survive both
  `uvicorn app.main:app` and Vercel (same entrypoint, named in
  `[tool.vercel]`). That means: no reliance
  on local disk, no in-process caches that assume a long-lived process, no
  background tasks — those wait for Phase 3.
- **League facts live in `app/leagues.py`,** nowhere else, and users can
  edit their own at `/app/leagues`
  ([docs/LEAGUE_SETTINGS.md](docs/LEAGUE_SETTINGS.md)). One `League`
  dataclass carries a league's size, roster slots and every scoring value —
  offense, individual defenders (IDP) and whole team defenses (D/ST), which
  are separate slots a league can start both of;
  the IDP board's per-event dicts and the mock room's JS config are both
  *generated* from it. Which defensive groups a league can start is derived
  from its slots, and its ADP column from its size — neither is configured
  separately, so neither can disagree with the roster. The verified numbers
  stay in [docs/LEAGUES.md](docs/LEAGUES.md).
- **Yahoo JSON gets flattened in `app/yahoo/parse.py`,** not in routes and not
  in the browser app. New resource, new extractor, new test fixture mirroring
  the real shape.
- `/api/raw/{path}` is the escape hatch for exploring unmodelled resources.
  Prefer adding an extractor over letting the browser app consume raw shapes.
- **Every served page is built with `skin.head()`.** It emits the head
  tags, the favicon, the theme boot and `home_bar()` in one place. Nine
  hand-written heads had already drifted — the alert board carried no
  favicon and three pages ignored the user's club. Installed as a PWA the
  app also has no address bar, so a page whose only exit is a text link is
  a dead end. `tests/test_navigation.py` walks a list of every
  server-rendered page, signed in *and* signed out — add a page, add it to
  that list. The ten: `/app/mine`, `/app/leagues`, `/app/mock`,
  `/app/mock/board`, `/app/nextup`, `/app/scorecard`, `/app/idp`,
  `/app/cheatsheet`, `/app/alerts300`, `/app/access`. `scripts/lint_docs.py`
  fails if that list and this one disagree.
- **Units have fences, and the fence is a test.** `app/` is a layer
  stack — kernel, data units, surfaces, composers — and
  `tests/test_boundaries.py` fails on a new upward or sideways import, or
  on any module touching another's private names. Its `KNOWN_BREACHES`
  list is a ratchet: it fails when a breach is added *and* when a listed
  one is fixed but not deleted, so it can only shrink. One worked unit
  contract: [docs/units/wire.md](docs/units/wire.md).
- **Serve-time edits to the app page are named transforms** in
  `app/feeds/page.py`, never inline `html.replace()` in `main.py`. Each
  reports the anchors it could not find, and `tests/test_page.py` asserts
  every one still fires against the committed `frontend/index.html` — a
  silent miss is the same failure as a control wired to nothing.
- **No stale data.** Every user-facing surface is live-polled, the owner's
  own judgement, or curated facts wearing an honest as-of stamp — nothing
  claims freshness it does not have. The audit and the plan for what is
  still curated: [docs/STALE_DATA.md](docs/STALE_DATA.md). A surface that
  goes live gets a `verify-live.yml` check in the same commit.
- **No false positives.** Never fabricate a judgement, a number, or a
  freshness label to make a surface look complete — an empty truthful
  section beats an invented one. When a call is genuinely uncertain, ask
  the owner instead of guessing. The standing list of known gaps and the
  fixes already made: [docs/GAP_REVIEW.md](docs/GAP_REVIEW.md).
- **Two stages, one codebase.** `main` deploys prod; the `beta` branch
  deploys a stable Vercel preview that wears a BETA badge and reads (never
  writes) the shared feed store. See
  [docs/ENVIRONMENTS.md](docs/ENVIRONMENTS.md) before touching deploy or
  store wiring.

## Working rules

- Tests must pass with no network and no Yahoo credentials.
- Keep this file updated: when a decision is made or the phase state changes
  materially, update the relevant section here.

## The validation gate — run this BEFORE starting new work

Not after. Every rule below was bought with a real failure on Aug 15-18;
none of them are hygiene for its own sake.

```bash
git fetch origin main && git log --oneline HEAD..origin/main   # 1
ruff check . && ruff format --check .                          # 2
pytest -q                                                      # 3
(cd frontend/lib && node --test)                               # 4
python3 -c "import glob,yaml;[yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]"  # 5
```

1. **Sync with `main` first.** Two sessions work this repo in parallel and
   have twice built the same feature simultaneously (Vegas lines, then the
   AI provider), each costing a real reconciliation. Check what landed
   before writing anything, and merge it in before starting.
2-5. Lint, format, both test suites, and workflow YAML. A workflow that
   fails to parse does not run at all, and nothing else in CI catches it.

**Then, after deploying:** run `verify-live.yml` and *read the log*, do not
just check the badge. Three separate bugs this week were green-and-broken:
a retired model endpoint returning 410, a sync silently deleting every
stored verdict, and two watchdog checks running twice. A green check means
the script exited 0, which is not the same as the thing working.

**Corollary — never trust a name you did not verify against the live API.**
The AI layer was built against a provider retired two weeks earlier, then
pointed at a model that no longer existed. Both were "known" facts. Ask the
endpoint what it actually offers; the model list is one HTTP call.

## State

Phase 2 complete as scaffolded: OAuth (authorize / exchange / refresh),
encrypted swappable token store, and read endpoints for leagues, teams,
rosters, draft results, scoreboard and transactions. Plus the browser client
in `frontend/lib/` and CI in `.github/workflows/ci.yml`.

847 tests green — 831 Python (`pytest`) and 16 JS (`cd frontend/lib && node --test`) —
lint and format clean. CI runs all of it plus a secret guard on every push
to main and beta.
Hosting decision and its Phase 3 cost: [docs/HOSTING.md](docs/HOSTING.md).

The served page reads live data: the `/app/data/feeds.json` overlay merges the
polled wire (impact-ranked, deduped, `first_seen`-stamped) into the page's own
startup fetch, and `mobile.js` decorates NEW badges and Out & returning wire
stamps onto the rendered rows. See docs/RESUME.md for the live-state detail.

`/app/mock` is the mock draft room (owner request, Aug 20): pick a league and
a slot, the other nine teams autopick from the live pool — market ADP with
each league's verified scoring leaned on it, defenders by their /app/idp
league-scored totals — or Autopilot drafts the owner's picks too, each with a
stated reason, rendered as a round-by-round plan. All simulation is labelled;
the engine has a headless smoke test — `tests/test_mock_engine.py` runs the
page's own JavaScript under node against the DOM stub in `tests/js/`,
drafting every league from both the turn and the wheel. CI pins node and
fails the build if that test skips itself. The Draft
analyzer links to it via mobile.js. The room wears the app's own modes
(Light/Cowboys/Titans/Dark via `ww_theme`), drafts RED_EYE at its real 12
seats, and its "Draft board ⧉" button opens the snake grid with hover
details in a new tab. The page's news overlay reads newest-first — impact
selects what shows, chronology orders it (owner call, Aug 20).

`/app/scorecard` grades the app against reality (owner ask, Aug 21): an
immutable ledger records every TD lean when it is made — an existing
entry is never overwritten, which is what makes it evidence rather than
opinion — and Sleeper's per-week box scores settle it later. It reports
**calibration**, not just a hit rate, because "said 78, hit 33" is the
finding a bare percentage hides. No rate is printed until real games are
behind it; pushes and unplayed games are excluded; prose surfaces
(capsules, verdicts, previews) stay explicitly unscored rather than
graded against an invented rubric. Ledger in its own Redis key so no sync
can reset the history to "no evidence".

`/app/nextup` is the pickup board (owner request, Aug 21): every starter
flagged out, the player measured to be behind him, how much work comes
loose, and the real latest wire post about the replacement. Depth is
computed in `app/feeds/depth.py` from Sleeper's '25 opportunity — usage
the stats reducer had been storing and nothing had joined up — so the
numbers are measured rather than the curated guesses the handcuff table
shipped with. Flags and wire posts live, workload labelled '25, nothing
projected.

The login gate (owner request, Aug 20): `/login` + an owner-managed email
allowlist at `/app/access` with one-time invite links — built, tested, and
**off by default**; the owner enables it with four Vercel env vars
([docs/ACCESS.md](docs/ACCESS.md) has the steps and the lockout escape
hatch). Sessions are signed cookies, invites are stored hashed, the
allowlist lives in its own Redis key so no sync can clobber it, and the
runner/watchdog pass with X-Sync-Token. `/api/*` deliberately stays open
(GAP_REVIEW #11). On top of it: `/app/leagues` lets each user describe
their own league — full custom scoring, not presets — and the mock room
and IDP board then score with it (docs/LEAGUE_SETTINGS.md); `/app/mine`
gives each signed-in user their own private layer (named text/CSV
documents, per-email Redis key),
and adding a user can email them the invite + app intro + league links
when SMTP env is set. **Passkeys** (Face ID / Touch ID) layer on top:
register from `/app/mine` after a normal sign-in, then the login page
signs you in with a face or fingerprint — discoverable credentials, user
verification required, public keys only, and the allowlist still governs
(revoking an email deletes its passkeys). Bound to the hostname, so a
custom-domain move means re-registering. All of it in docs/ACCESS.md.

Not yet done: verified against a live Yahoo account — blocked on Yahoo's
fantasy-access approval (see docs/RESUME.md), not on code.

Phase 3 (cron jobs polling feeds on their budget intervals, a database, and web
push for the Settings rules) builds on this service — hence the Dockerfile and
the store interface.

Phase 4 is **Productize** — the transition from "owner + 5 testers, free" to
something sellable: [docs/PRODUCTIZE.md](docs/PRODUCTIZE.md) has the real
costs (~$21/mo floor: Vercel Pro, since Hobby is non-commercial, plus a
~$10/yr domain), the licensing blockers, and the *order*. **Planning only —
do not build from it without the owner asking.** One item there is
time-sensitive rather than money-sensitive: passkeys are bound to the
hostname, so the custom domain should be bought and pointed before more
people register Face ID, or they all re-register.
