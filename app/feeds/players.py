"""Tag feed items with the players they mention.

This is what separates a news reader from a draft tool: 141 headlines a day is
noise until you can ask "which of these are about someone on my board".

Precision over recall, deliberately. A wrong tag is worse than a missing one --
it puts a headline about a practice-squad lineman onto your RB1's card. So:

- Full names ("Puka Nacua") always match.
- A bare surname matches only when it is UNIQUE among active skill players.
  "Pearce" resolves; "Smith" never does, because guessing which Smith is worse
  than saying nothing.
- Suffixes are indexed both ways, since feeds are inconsistent about "Jr."

The Sleeper dump is 14MB, so it is fetched at most once a day and reduced to a
compact index. Sleeper's docs ask callers not to poll it more often than that.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
FANTASY_POSITIONS = {"QB", "RB", "WR", "TE", "K"}
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

_WORD_RE = re.compile(r"[A-Za-z0-9']+")

# Surnames that are also ordinary English words. Matching these bare produced
# real errors against live feeds: "sources heard" -> Braylon Heard,
# "in the slot" -> ... Full names still resolve; only the bare form is refused.
COMMON_WORD_SURNAMES = frozenset(
    """
    heard chase love small brown white black green gray grey young old best
    british french irish moore price rice cook cooks fields flowers rivers
    banks bell bush camp carr coleman cross dean diggs down first free good
    hall hand hart hill hunt johnson jones king knight land long love mann
    may mills moss news night park parks pitts pope post reed rich ridge
    rose sanders sharp sharpe shepherd short slay speed stone strong swift
    tucker walker ward waters watts west wise wood woods work
    """.split()
)


@dataclass(slots=True)
class Player:
    id: str
    name: str
    position: str
    team: str | None
    injury_status: str | None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "position": self.position,
            "team": self.team,
            "injury_status": self.injury_status,
        }


def normalize(text: str) -> str:
    """Fold accents and lowercase. 'Amon-Ra St. Brown' -> 'amon ra st brown'."""
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return folded.lower().replace("-", " ").replace(".", " ")


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(normalize(text))


def _cased_tokens(text: str) -> list[tuple[str, bool]]:
    """(normalized_token, was_capitalised) pairs, preserving order.

    Case is the cheapest available signal against common-word surnames:
    "sources heard" is lowercase, "Braylon Heard" is not.
    """
    raw = _WORD_RE.findall(text.replace("-", " ").replace(".", " "))
    return [(normalize(tok), tok[:1].isupper()) for tok in raw]


def build_index(raw: dict) -> dict:
    """Reduce Sleeper's dump to what matching needs.

    Returns {"by_name": {key: player_dict}, "players": {id: player_dict}} where
    key is a space-joined normalized name. Ambiguous surnames are excluded
    rather than resolved arbitrarily.
    """
    players: dict[str, dict] = {}
    full_keys: dict[str, str] = {}
    surname_hits: dict[str, set[str]] = {}

    for pid, rec in raw.items():
        if not rec.get("active"):
            continue
        position = rec.get("position")
        name = rec.get("full_name") or ""
        if not name:
            continue

        # Ambiguity is judged across EVERY active player, not just fantasy
        # positions -- otherwise "adding Arnold" resolves to Dan Arnold (TE)
        # when the story is about Terrion Arnold, a cornerback the index would
        # never have seen. Non-fantasy players poison the surname, by design.
        if position not in FANTASY_POSITIONS:
            surname = [p for p in _tokens(name) if p not in SUFFIXES]
            if surname:
                surname_hits.setdefault(surname[-1], set()).add(pid)
            continue

        player = Player(
            id=pid,
            name=name,
            position=position,
            team=rec.get("team"),
            injury_status=rec.get("injury_status"),
        ).to_dict()
        players[pid] = player

        parts = _tokens(name)
        if not parts:
            continue

        # Index the full name, and the name minus any suffix, so "James Pearce"
        # matches a record stored as "James Pearce Jr.".
        full_keys[" ".join(parts)] = pid
        stripped = [p for p in parts if p not in SUFFIXES]
        if stripped and stripped != parts:
            full_keys[" ".join(stripped)] = pid

        surname = stripped[-1] if stripped else parts[-1]
        surname_hits.setdefault(surname, set()).add(pid)

    # A surname is usable only if exactly one active player owns it league-wide
    # and it is not an ordinary English word.
    by_name = dict(full_keys)
    surnames: dict[str, str] = {}
    for surname, ids in surname_hits.items():
        if len(ids) != 1 or surname in COMMON_WORD_SURNAMES:
            continue
        pid = next(iter(ids))
        if pid in players and surname not in by_name:
            surnames[surname] = pid

    return {"by_name": by_name, "surnames": surnames, "players": players}


def find_players(text: str, index: dict, limit: int = 6) -> list[dict]:
    """Return the players mentioned in `text`, best-effort, in first-seen order."""
    by_name = index.get("by_name", {})
    surnames = index.get("surnames", {})
    players = index.get("players", {})
    cased = _cased_tokens(text)
    words = [w for w, _ in cased]

    found: list[str] = []
    seen: set[str] = set()

    def record(pid: str) -> None:
        if pid not in seen:
            seen.add(pid)
            found.append(pid)

    i = 0
    while i < len(words):
        # Longest match first: four words ("amon ra st brown") down to two.
        matched = False
        for span in (4, 3, 2):
            if i + span > len(words):
                continue
            pid = by_name.get(" ".join(words[i : i + span]))
            if pid:
                record(pid)
                i += span
                matched = True
                break
        if matched:
            continue

        pid = surnames.get(words[i])
        if pid:
            capitalised = cased[i][1]
            # A capitalised word followed by another capitalised word is far
            # more likely a first name: "Chase Bisontis" is not Ja'Marr Chase.
            next_is_capitalised = i + 1 < len(cased) and cased[i + 1][1]
            if capitalised and not next_is_capitalised:
                record(pid)
        i += 1

    return [players[pid] for pid in found[:limit] if pid in players]


def tag_items(items: list[dict], index: dict) -> list[dict]:
    """Attach a `players` list to each item. Mutates and returns the list."""
    for item in items:
        text = f"{item.get('title', '')} {item.get('summary', '')}"
        item["players"] = find_players(text, index)
    return items


async def fetch_index(timeout: float = 90.0) -> dict:
    """Download and reduce the Sleeper player dump (~14MB)."""
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(
            PLAYERS_URL, headers={"User-Agent": "FBBible/0.1 (personal fantasy tool)"}
        )
    response.raise_for_status()
    index = build_index(response.json())
    log.info("player index: %d players, %d name keys", len(index["players"]), len(index["by_name"]))
    return index
