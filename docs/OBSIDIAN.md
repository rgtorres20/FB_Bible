# Obsidian — free two-way sync

Goal: Claude Code writes to this repo from a cloud container; Obsidian on
your machine picks the changes up, and your edits come back. No paid Obsidian
Sync — the transport is git, which you already have.

## The one structural decision

**Open `FB_Bible` (the repo root) as the vault — not `docs/`.**

The Obsidian Git plugin wants a git repository at the vault root. Its README
does not promise support for a vault nested *inside* a repo, and that was not
verifiable from here, so we removed the question instead of betting on it.
`.obsidian/` therefore lives at the repo root.

The cost is that Obsidian's file explorer also shows `app/`, `tests/` and the
rest. The benefit is that `CLAUDE.md` — the schema for the whole wiki — is
inside the vault, where the pattern says it belongs. `docs/` is still the wiki;
it is just a folder in a larger vault.

## Setup, once

1. **Install Obsidian** — free, obsidian.md. Desktop.
2. **Clone the repo** somewhere ordinary. *Not* inside iCloud Drive, Dropbox
   or OneDrive: file-level cloud sync racing git on `.git/` corrupts repos.
   ```bash
   git clone https://github.com/rgtorres20/FB_Bible.git
   ```
3. **Open it as a vault** — Obsidian → *Open folder as vault* → pick `FB_Bible`.
   It will find the committed `.obsidian/app.json` and adopt the settings.
4. **Install the Git plugin** — Settings → Community plugins → *Turn on
   community plugins* → Browse → search **Git** (by Vinzent03) → Install →
   Enable.
5. **Configure it** — Settings → Git:
   - *Auto pull on startup* → **on**
   - *Auto pull interval* → **10** minutes
   - *Auto backup after file change* (commit + push) → **10** minutes
   - *Commit message* → something like `obsidian: {{date}}`

Authentication is plain HTTPS with a GitHub personal access token
(fine-grained, **Contents: read and write**, scoped to this repo). SSH also
works on desktop; the plugin does not support SSH on mobile.

## What then happens

- I push to `main`. Within 10 minutes Obsidian pulls it and your pages update.
- You edit in Obsidian. Within 10 minutes it commits and pushes.
- Next session I `git pull` and see your edits.

**Anything unpushed does not exist to the next session.** The container that
runs Claude Code is destroyed when the session ends; git is the only shared
surface.

## Conflicts

Both sides can edit the same file, and git will conflict rather than guess.
Keep it rare and it stays a non-issue:

- Hit **Pull** (command palette → *Git: Pull*) before an editing session.
- Tell me when you have edited a page, so I pull before touching it.
- If a conflict does land, Obsidian shows the `<<<<<<<` markers in the file —
  resolve it in the editor and commit.

## Mobile — the honest version

Free two-way sync on iPhone is the weak link, and this is worth knowing before
you spend an evening on it. Per the plugin's own README, on mobile it has:

- no SSH authentication (token over HTTPS only)
- **limited repo size, because of memory restrictions**
- no rebase strategy, no submodules
- and it warns Obsidian "may crash on clone/pull, create buffer overflow
  errors, or run indefinitely" on larger repos

This repo is not tiny — it carries the full app, tests and git history. Cloning
it on a phone is exactly the case that README warns about. Realistic options:

- **Desktop only** for editing; read on the phone via the GitHub app. Free,
  and it works today.
- **Obsidian Sync** (paid) if phone editing turns out to matter.
- **A second, tiny vault repo** holding only the wiki pages, cheap enough for a
  phone to clone — at the cost of the docs no longer living beside the code.

Start with desktop. Only pay for a problem you have actually hit.
