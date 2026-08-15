# frontend/

The browser half of the Fantasy Bible. Right now this directory holds only the
API client — **the app itself is still in the Claude design project and has not
been brought over yet.** That is the last thing standing between this repo and
being the whole project.

## Layout

```
frontend/
├── index.html      <- Fantasy Bible.dc.html goes here (not yet present)
├── data/
│   └── feeds.json  <- the sync-updated feeds (not yet present)
└── lib/
    └── fbApi.js    <- API client for the server. Already here, tested.
```

## Bringing the app over

The design project is already connected to this repo, so it can commit its own
files. Paste this into that chat:

> Commit these to the connected repo: `Fantasy Bible.dc.html` as
> `frontend/index.html`, and `data/feeds.json` as `frontend/data/feeds.json`.
> Keep the contents byte-identical — this is a move, not a rewrite.

Rename to `index.html` on the way in. The space in "Fantasy Bible.dc.html" has
to be percent-encoded in URLs and breaks a surprising number of static hosts.

Full checklist, including everything else that would otherwise be stranded:
[../docs/MIGRATION.md](../docs/MIGRATION.md).

## After it lands

Two wiring steps, neither of which needs the design project:

1. **Point the page at the server.** Add the client and construct it with the
   deployed origin — see [lib/README.md](lib/README.md) for the drop-in snippet
   and the method list.
2. **Set `CORS_ORIGINS`** on the server to wherever this page is served, or the
   browser blocks every call.

Then the Draft Analyzer reads `/api/leagues/{key}/draft` instead of hand-typed
picks, and the My-team panels read `/api/teams/{key}/roster`. That is Phase 2
actually finished, as opposed to merely built.

## Serving it

It is a static page — any static host works, including Vercel alongside the
API. Whatever you pick must be **https**, because the page will call an https
API and browsers block mixed content.
