# Data licensing — what constrains a commercial version

Not legal advice. These are the published terms as of **Aug 14 2026**, recorded
because they shape architecture, not just paperwork. A real sale needs counsel
and, in at least two cases below, a signed agreement with the provider.

The project's original note — *"user doesn't care about licensing constraints"*
— was written when this was a personal tool. It no longer holds: selling is on
the table, so the constraints are tracked here.

## Current posture

**Personal, single-user, not distributed.** One Yahoo account (the owner's)
links the leagues. Nothing is sold, nothing is served to third parties. Under
that posture the terms below are satisfied — the issues are all triggered by
commercialization or by other people using it.

## Yahoo requires approval before any access at all

**Discovered 2026-08-15, the hard way.** Creating a Yahoo app is no longer
enough. The developer console has removed the Fantasy Sports API permission
from both the create and edit forms, and requesting `scope=fspt-r` against an
unapproved app returns:

    {"detail":"Yahoo denied the request: invalid_scope invalid scope"}

Access is now gated behind an application at <https://sports.yahoo.com/developer>:
submit your organisation, product and intended use cases; Yahoo reviews and may
ask follow-ups; approved applicants get next steps.

Nothing in this repo is misconfigured -- the OAuth flow, redirect URI,
credentials and token store were all verified working. Yahoo is refusing the
scope, and no code change can route around that.

Two further terms from that page, both new obligations:

- **Attribution is mandatory**: "Fantasy data provided by Yahoo Fantasy" must
  be displayed wherever their data appears. Same class of requirement as the
  Sleeper attribution already in the Alerts panel.
- **One account per developer**; automated multi-account creation is
  prohibited. Reinforces the single-user decision, and is another obstacle in
  front of ever opening this up to "anyone".

## Yahoo Fantasy Sports API

Source: <https://legal.yahoo.com/us/en/yahoo/terms/product-atos/apiforydn/index.html>

| Term | Effect here |
|---|---|
| Shall not *"derive income from the use or provision of the Yahoo APIs… unless… Yahoo gives prior, express, written permission"* | **Blocks selling** any version that calls Yahoo. Needs a written agreement with Yahoo first. |
| Must *"immediately remove… any Yahoo user data obtained through the Yahoo APIs… within 24 hours after the time at which you obtained the data"* | **Architectural.** Phase 3 plans cron jobs writing feeds to a database. Yahoo-sourced rows need a ≤24h TTL and a purge job. Non-Yahoo feeds (Sleeper, news) are unaffected. |
| May not disclose or store Yahoo user data *"in any data repository that enables any third party… access unless… expressly permitted by the Yahoo user"* | **Blocks naive multi-user.** Each user's Yahoo data must be isolated and consented, not pooled. |
| Shall not use the APIs *"in a product or service that competes with products or services offered by Yahoo"* | A paid fantasy draft tool plausibly competes with Yahoo Fantasy. Worth a direct read before investing in a sale. |
| No hard rate cap; must not exceed *"reasonable request volume"* | Fine at current scale. |

The 24-hour rule is the one that changes code. It is not a paperwork problem —
build the TTL in when Phase 3 lands, not after.

## Sleeper API

Source: <https://docs.sleeper.com/>

| Term | Effect here |
|---|---|
| *"free to use for non-commercial purposes"*; commercial use requires contacting them to discuss licensing | **Blocks selling** without a Sleeper agreement. |
| *"Please give attribution to Sleeper you are using our trending data"* | **Applies today.** The Alerts panel shows Sleeper trending adds/drops. Attribution should be visible in the UI now, commercial or not. |
| Stay under ~1000 calls/minute or risk an IP block | Fine at current scale; matters if Phase 3 cron fans out. |

## Not yet reviewed

These are used or planned as sources and have not been checked. Each needs the
same treatment before any sale:

- ESPN (draft kit, scoreboard), NFL.com (schedules), CBS, Rotowire,
  NBC/Rotoworld, Pro-Football-Reference, PFF, FantasyPros, TeamRankings —
  currently consumed via chat-sync research rather than API, which is a
  different (not automatically safer) posture.
- DraftKings salary data — planned for Phase 4 FFBets.
- NFL team names, logos and marks — factual stats are one thing; trademarks in
  a sold product are another. **Live instance of this today:** Titans mode's
  watermark is the club's sword mark, supplied by the owner Aug 20 for their
  own personal build (`frontend/assets/titans-sword.png`, wired in
  `frontend/mobile.css`). Fine for personal use; before any distribution or
  sale it must be swapped back to an original emblem — the stand-in this
  repo shipped first is preserved in git history (mobile.css prior to the
  Aug 20 swap) and can be restored in one commit.

## Practical order of operations

1. **Now:** build and use it yourself. Nothing here prevents that.
2. **Before anyone else uses it:** per-user data isolation and consent
   (Yahoo's third-party-access clause), and Sleeper attribution in the UI.
3. **Before selling:** written permission from Yahoo, a Sleeper commercial
   licence, and a source-by-source review of the table above.

## Repository licence

Intentionally **no open-source LICENSE file** — the work stays "all rights
reserved" by default, which is the right posture for an asset that might be
sold. Do not add an OSS licence without deciding that deliberately.
