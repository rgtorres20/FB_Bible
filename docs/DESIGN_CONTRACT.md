# What the server needs `index.html` to keep

The browser app is generated in the Claude Design project and lands here
as `frontend/index.html`, byte-identical on disk (docs/MIGRATION.md).
Everything the backend adds — the mark, the club theme, live ADP, live
odds, the real league names — is a **serve-time string edit** that finds
an exact literal and replaces it.

So a resync from the design project is the highest-risk event in this
repo: rename one of these strings and the server silently loses a
feature. The page still renders. Nothing errors.

**Since Aug 21 it is no longer silent.** `app/feeds/page.py` reports
every anchor it could not find, and `tests/test_page.py` fails when any
transform stops firing against the committed `index.html`. After a
resync, run the suite — it names exactly which edits broke.

```bash
/usr/local/bin/python3 -m pytest -q tests/test_page.py tests/test_board.py \
    tests/test_vegas.py tests/test_stats.py
```

## The literals

Owned by `app/feeds/page.py` — this list is complete for that module:

| Anchor | Why the server needs it |
| --- | --- |
| `</head>` | Where the mark, theme boot, mobile.css and mobile.js go |
| `import("./frontend/lib/fbApi.js")` | Rewritten to `./lib/` — the design project's layout is not the served one |
| `vegas: VEGAS,` | Rebound to the live odds feed |
| `gdMode: "build",` | FFBets opens on Predictions |
| `[{ id: "build", label: "Build a team" }, …]` | Build-a-team tab is shelved |
| `<option value="cowboys">★ Cowboys mode</option>` | Becomes ★ My team |
| `themeLabel: s.theme === "cowboys" ? "★ Cowboys mode"` | The matching label |
| `if (th === "dark" \|\| th === "light" \|\| th === "cowboys")` | Restore guard gains `team` |
| `theme: "light"` | The app opens on the club theme, not light |
| `skin: "cowboys",` | Stops the page forcing a Dallas skin on everyone |
| `Sunday Gravy` / `The Trenches` / `Gravy` / `Trenches` | Renamed to NDDPL / RED_EYE |
| `</body>` | Where the BETA badge goes on preview deploys |

Three more modules bind to their own literals — `board.py` (the
`RAW_BOARD` array and the ADP column), `vegas.py` (the odds table,
caption and schedule) and `stats.py` (the team-intel usage reads). Their
own test files are the authority on those; they are not re-listed here
because a partial list read as complete is worse than none.

## The counter-intuitive part

**Do not "fix" the stale-looking strings in the design document.**

`Sunday Gravy`, `The Trenches` and `Cowboys mode` are wrong on the page
and right in the source: the server rewrites them at serve time, so the
design document is *supposed* to still say them. Correcting them in
design breaks the rename — the anchor disappears, the transform misses,
and the served page keeps whatever the design says.

If a rename genuinely should move into the design document, delete the
matching transform from `page.py` in the same change. One or the other
owns each string, never both.

## Adding a control that has to *do* something

A control's appearance lives in the design document. What it **does**
lives here. Those are separate changes and both are required.

Shipping the first without the second is how the Trusted-sources panel
ended up with five sliders wired to nothing for weeks
([WEIGHTS.md](WEIGHTS.md)) — the panel was convincing about influence it
did not have. A redesign that groups those sliders more sensibly, without
the server-side change, makes that problem *more* convincing, not less.

So for anything with behaviour, the design side needs to hand over:

1. **The anchors** — the exact ids, option values or literal strings the
   server can bind to.
2. **The storage keys** it reads and writes. `ww_*` and `fb_*` keys are
   immutable (CLAUDE.md); a new one is a deliberate decision, not a
   detail.
3. **What each control is supposed to change**, in one sentence per
   control, concrete enough to write a test from — *"raising this moves
   player X above player Y on the draft board"*, not *"weights the
   source"*.

Point 3 is the one worth insisting on. Without it there is no expected
result, so there is no test, so nobody can tell a working control from a
dead one.
