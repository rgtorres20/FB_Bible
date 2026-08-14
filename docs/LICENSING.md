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
  a sold product are another.

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
