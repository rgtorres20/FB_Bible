"""As-of stamps for the lists nobody polls.

Two tabs on the app page are hand-written constants that no feed touches:
the **Sleepers** list (`TARGETS`, 19 rows of analysts' picks transcribed
from PFF, Yahoo, Bleacher Report and beat reports) and the **Backup RBs**
table (`CUFFS`, 32 rows of usage splits with no source attribution at
all). Both were last revised on 2026-08-14.

Owner, Aug 25: "we need to add dates so i know if this is latest or
preseason". Exactly the right question, and the honest answer was not on
screen anywhere -- the rows carry a scattering of "Thu Aug 13" inside
prose, and the tab headers said nothing. Eleven days and a round of
preseason games later, a reader had no way to tell whether they were
looking at this week's thinking or last month's.

**The date is committed, and drift is made impossible rather than
discouraged.** A stamp somebody has to remember to update is the same
class of bug as the frozen "Today" timestamps: it starts true and rots
quietly. So each entry carries a digest of the block it describes, and
`tests/test_curated.py` recomputes it from the real `frontend/index.html`
-- edit a list without moving its date and the suite fails, naming the
list.

Git is where the date comes from (`git log -L` on the constant's own
lines), not from a guess. It cannot be read at runtime: Vercel serves a
build, not a checkout.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date

# The lists this covers, with the date each was last genuinely revised and
# a digest of its content. Update BOTH together -- the test enforces it.
CURATED: dict[str, dict] = {
    "TARGETS": {
        "label": "Sleepers",
        "as_of": date(2026, 8, 14),
        "sha": "2d4b9c6f4926c31f",
        "source": "from PFF, Yahoo, Bleacher Report and beat reports",
    },
    "CUFFS": {
        "label": "Backup RBs",
        "as_of": date(2026, 8, 14),
        "sha": "4da69f1c4fbe6dda",
        "source": "usage splits are estimates, not measured",
    },
}


def block(html: str, name: str) -> str:
    """The `const NAME = [...]` block, exactly as the page carries it."""
    found = re.search(r"const " + re.escape(name) + r" = \[.*?\n\];", html, re.S)
    return found.group(0) if found else ""


def digest(html: str, name: str) -> str:
    """A short content hash, so a silent edit cannot keep an old date."""
    body = block(html, name)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16] if body else ""


def age_words(as_of: date, today: date) -> str:
    days = (today - as_of).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


def stamp(name: str, today: date) -> str:
    """The one line a reader needs: when, and how old that is.

    Says "read by hand" rather than dressing a transcription up as a feed.
    The point of the stamp is that the reader can distrust it.
    """
    entry = CURATED.get(name)
    if not entry:
        return ""
    return (
        f"Read by hand · as of {entry['as_of']:%b %-d, %Y} "
        f"· last revised {age_words(entry['as_of'], today)}"
    )


_ANCHORS = {
    # Each tab's own opening <div>, which is the first thing under the
    # kicker and so where a reader looks before reading a single row.
    "TARGETS": (
        '{{ isWaivers }}" hint-placeholder-val="{{ false }}">\n'
        '      <div style="padding-bottom:var(--space-8);">'
    ),
    "CUFFS": (
        '{{ isCuffs }}" hint-placeholder-val="{{ false }}">\n'
        '      <div style="padding:0 var(--space-8) var(--space-8);">'
    ),
}


def _banner(text: str) -> str:
    return (
        '<div style="padding:8px var(--space-8); font-size:11px; '
        "border-bottom:1px solid var(--color-neutral-300); "
        'color:var(--color-neutral-700);">' + text + "</div>"
    )


def inject(html: str, today: date) -> tuple[str, int]:
    """Stamp both hand-read tabs with the date they were last revised.

    Owner, Aug 25: "we need to add dates so i know if this is latest or
    preseason". Neither tab said anything about its own age, and both had
    been standing since Aug 14 -- through a round of preseason games.

    Per tab, not once for the page: they are separate lists and will not
    stay in step once one of them starts being maintained.
    """
    done = 0
    for name, anchor in _ANCHORS.items():
        if anchor not in html:
            continue
        entry = CURATED.get(name) or {}
        line = stamp(name, today)
        if entry.get("source"):
            line += " \u00b7 " + str(entry["source"])
        html = html.replace(anchor, anchor + _banner(line), 1)
        done += 1
    return html, done
