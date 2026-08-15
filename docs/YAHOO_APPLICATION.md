# Yahoo Fantasy API access application — ready to submit

The `invalid_scope` on `/auth/yahoo/login` is not a bug and there is no
support-ticket route for it: Fantasy API access now requires an approved
application at <https://sports.yahoo.com/developer> ("Apply for access").
This file is the submission, written so it can be pasted field-by-field.

Reference facts:

- Registered app: `Fantasy Bible` — developer.yahoo.com/apps/XSJqPLxv
- Redirect URI: `https://fb-bible-torro2.vercel.app/auth/yahoo/callback`
- Scope requested: `fspt-r` (read-only; the app never writes lineups)

## Organization / who is applying

> Individual developer (Robert Torres). Personal project, not a company.

## Product description

> Fantasy Bible is a personal draft-preparation dashboard for the two Yahoo
> Fantasy Football leagues I play in. It aggregates public NFL news (ESPN,
> NBC Sports, CBS, Rotowire RSS) with my own notes, and I want to add
> read-only data from my own Yahoo leagues so my roster, draft results and
> league transactions appear alongside that news instead of being typed in
> by hand.

## Intended use of the API

> - Read-only (`fspt-r`) access to the two leagues my own Yahoo account is a
>   member of: league settings, teams, rosters, draft results, scoreboard
>   and transactions.
> - Single user (myself); one OAuth account; no data shown to anyone else.
> - Polling is on-demand when I open the app, plus at most hourly background
>   refresh; volume is a handful of requests per hour.
> - Yahoo data is held in a private encrypted store and expired within 24
>   hours, per the API terms.
> - "Fantasy data provided by Yahoo Fantasy" attribution will be displayed
>   wherever Yahoo data appears.
> - No commercial use, no redistribution, no automated account creation.

## Technical contact

> rgtorres20@icloud.com
