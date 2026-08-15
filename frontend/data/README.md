# frontend/data/

`feeds.json` belongs here. It is not in the repo yet — it currently lives in
the Claude design project.

## What it holds

The chat-synced feeds the app loads at startup, which override the in-file
`*_SEED` constants: `alerts`, `news`, `scout`, `weekrev`, `meta`, `rotowire`.
These are researched during chat syncs from the blueprint's trusted sources
(NBC/Rotoworld, Rotowire, Yahoo's wire, CBS, ESPN, Schefter), each carrying its
own source and timestamp.

This is **not** the Sleeper live-wire data. That is fetched at runtime from
`api.sleeper.app` and cached in `localStorage` under `ww_live`.

## Two rules for anything added here

**Never put Yahoo data in this file.** Yahoo requires user data be deleted
within 24 hours of being obtained (see [../../docs/LICENSING.md](../../docs/LICENSING.md)),
and a file committed to git is permanent by definition. Yahoo data is fetched
live from the server and, if cached browser-side at all, goes through
`createYahooCache` in [../lib/fbApi.js](../lib/fbApi.js), which expires it.

**Sleeper trending data needs visible attribution** wherever it is displayed.
That applies today, not just if the project is ever sold.
