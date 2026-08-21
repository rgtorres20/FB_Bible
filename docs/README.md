# FB Bible — the vault

This folder is both the project's docs and an **Obsidian vault**. Open
`FB_Bible/docs` as a vault and these pages are the wiki; browse the same
folder on GitHub and they are ordinary markdown. Both have to keep working,
which is the only real constraint on how pages are written (see *Conventions*).

The schema for the whole thing is [../CLAUDE.md](../CLAUDE.md) — the rules
that bind code, and the pointer to every page below.

## Map

**Ground truth — facts the code must agree with**
- [LEAGUES.md](LEAGUES.md) — the three leagues, verified from Yahoo settings pages
- [LEAGUE_SETTINGS.md](LEAGUE_SETTINGS.md) — how a user describes their own league
- [BRAND.md](BRAND.md) — the mark, the palette, the swap procedure

**Decisions and designs**
- [WEIGHTS.md](WEIGHTS.md) — the three weight families *(design only, not built)*
- [PHASE2_SPEC.md](PHASE2_SPEC.md) — scope of the Yahoo link
- [HOSTING.md](HOSTING.md) · [ENVIRONMENTS.md](ENVIRONMENTS.md) — where it runs, prod vs beta
- [LICENSING.md](LICENSING.md) — verified terms; what selling would require
- [PRODUCTIZE.md](PRODUCTIZE.md) — Phase 4 costs and order *(planning only)*

**Standing audits — these are lint reports written by hand**
- [STALE_DATA.md](STALE_DATA.md) — what is live, what is still curated
- [GAP_REVIEW.md](GAP_REVIEW.md) — known gaps and the fixes already made

**Operations**
- [ACCESS.md](ACCESS.md) — login gate, invites, passkeys
- [YAHOO_SETUP.md](YAHOO_SETUP.md) · [YAHOO_APPLICATION.md](YAHOO_APPLICATION.md)
- [RESUME.md](RESUME.md) — live state, and what is blocked on what
- [MIGRATION.md](MIGRATION.md) · [APP_NOTES.md](APP_NOTES.md)

## Conventions

These exist so a page reads correctly in Obsidian *and* on GitHub, and so a
lint pass can check it later.

- **Standard markdown links, not wikilinks.** `[LEAGUES.md](LEAGUES.md)`, not
  `[[LEAGUES]]`. Wikilinks render as literal brackets on GitHub, which would
  break every cross-reference in `CLAUDE.md`. The committed
  `.obsidian/app.json` sets this, so Obsidian writes links this way by default.
- **A claim about the code names the file that proves it.** "603 tests" is a
  claim; "603 tests (`pytest -q`)" is a checkable one. Anything a lint pass
  cannot verify against the tree will eventually drift — the test count in
  `CLAUDE.md` was hand-corrected three times in one day.
- **Curated facts carry an as-of date.** The repo rule is no stale data; a
  page is a surface like any other.
- **Design pages say so in the first line.** `WEIGHTS.md` opens with
  *"Status: design. Nothing here is built yet."* — so nobody builds from it
  by accident.

## The line that matters

Karpathy's wiki pattern assumes sources are immutable and knowledge compounds.
Half of this product is a **live wire** — injury status, ADP, odds, snap counts
— where the new value *replaces* the old one.

So: **durable claims get a page; live state never does.** A page that says
"Nabers questionable, hamstring" is a liability the moment it is wrong, and
writing it here would violate the repo's own no-stale-data rule. Live state is
queried at render time and stamped with when it was fetched.

## Working on it from two sides

Claude Code writes here from a cloud container that is destroyed after each
session; Obsidian writes here from your machine. Neither can see the other's
disk, so **git is the sync** — pull before an editing session, push after.
Anything unpushed does not exist as far as the next session is concerned.
