"""The small lists a reader curates, kept with their account.

Owner, Aug 26: *"i see that back up running backs list does not save for
users why make a list you cant save"*, and then the general form of it:
*"when i log into other devices i dont see my changes"*.

Both are the same defect. The design document keeps fourteen things in
`localStorage`, and the ones that are the reader's own work -- the order
they put the backup running backs in, the rows they cleared, their draft
queue, who they have marked taken -- were therefore pinned to one
browser. Sign in on a phone and the app has never met you.

A list you cannot save is not a list, and a list that saves to one device
is a list you lose when you draft from the laptop instead.

WHAT FOLLOWS THE ACCOUNT AND WHAT DOES NOT. Only what a person *made*.
Appearance (`ww_theme`, `ww_skin`, `fb_team`) stays per device on
purpose: a phone in the dark and a desk monitor are different rooms, and
CLAUDE.md pins those two as immutable storage keys anyway. Caches
(`ww_live`) and the developer's API override (`ww_api_base`) are not
anybody's work. `ww_my_sleepers` is absent deliberately -- the sleepers
list already has its own route and its own store, and a second writer for
the same list is how the two of them start disagreeing.

The transport is deliberately dumb: these are opaque strings written by
the page's own code, and this module does not parse them. It decides
WHICH keys travel and how much of them, never what they mean. That keeps
the design document free to change what it stores in `ww_queue` without
this file needing to know.
"""

from __future__ import annotations

# In the user's own blob, beside `ranklists`, `rank_active` and `sleepers`.
KEY = "prefs"

# The keys that are the reader's own work. Everything else the page
# stores stays on the device it was stored on.
MANAGED = (
    "ww_cuff_order",
    "ww_cuff_hidden",
    "ww_my_teams",
    "ww_queue",
    "ww_taken",
    "ww_draft_slot",
    "ww_scout_dismissed",
    "ww_src_w",
    "ww_src_weight",
    "ww_league_weight",
)

# Caps, chosen rather than measured -- docs/ASSUMPTIONS.md. One value is
# generous for the biggest of these (a 300-name `ww_taken` is ~6KB), and
# the total bounds what one account can push into a blob that is loaded
# on every page render.
MAX_VALUE = 64 * 1024
MAX_TOTAL = 256 * 1024


def stored(user_data: dict | None) -> dict[str, str]:
    """This reader's saved values, ignoring anything unrecognised.

    Filtered on the way OUT as well as in: `MANAGED` shrinking must drop
    a retired key from the page rather than keep replaying it.
    """
    saved = (user_data or {}).get(KEY)
    if not isinstance(saved, dict):
        return {}
    return {k: v for k, v in saved.items() if k in MANAGED and isinstance(v, str)}


def merge(user_data: dict | None, incoming: dict | None) -> dict[str, str]:
    """Fold a write into what is already saved.

    A merge rather than a replace, because two tabs are two writers: the
    draft board open on a laptop and the cuffs tab open on a phone would
    otherwise take turns deleting each other's work. Each key is written
    whole -- they are opaque strings -- but a key nobody touched survives.

    An oversized value is dropped rather than truncated. Half a JSON
    array is not a smaller list, it is a corrupt one, and the page would
    read it back as an empty list and quietly lose the lot.
    """
    out = dict(stored(user_data))
    for key, value in (incoming or {}).items():
        if key not in MANAGED or not isinstance(value, str):
            continue
        if len(value.encode("utf-8")) > MAX_VALUE:
            continue
        out[key] = value

    # Oldest-first eviction is not available -- these are unordered and
    # equally wanted -- so a blob over the cap keeps the smallest values,
    # which loses the fewest lists.
    while sum(len(k) + len(v) for k, v in out.items()) > MAX_TOTAL and out:
        biggest = max(out, key=lambda k: len(out[k]))
        del out[biggest]
    return out
