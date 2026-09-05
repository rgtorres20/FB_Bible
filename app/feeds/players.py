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
from datetime import UTC, datetime

import httpx

log = logging.getLogger(__name__)

# Sleeper's injury vocabulary, and what each value means for a lineup.
# Kernel, because two units need the same answer: `depth` decides whether
# a starter's absence is a pickup trigger, and `board` decides which
# badge a draft row wears. Two copies is how one of them goes stale.
OUT_FLAGS = frozenset({"Out", "IR", "PUP", "Sus", "NA", "Doubtful", "DNR"})

# Of those, the ones that are a RESERVE DESIGNATION rather than this
# week's game status. Owner's rule, Aug 22: "if they are out for season
# drop off list, if they are only out for a few weeks leave."
#
# The honest caveat, because it decides how far this can be trusted:
# **Sleeper publishes no "out for the season" field.** `injury_status`
# says what a player is designated as, never for how long. A player on
# IR may be season-ending or may be designated to return; nothing in the
# data distinguishes them.
#
# So the line is drawn where the data actually draws one -- between a
# reserve list, which in the NFL carries a multi-week minimum and takes a
# player off a draft board, and a weekly game status, which does not.
# That is the closest faithful reading of the rule, and it is stated
# rather than presented as a season-ending judgement the app cannot make.
#
# It is also self-correcting: the flag is live, so a player who comes off
# IR reappears on the next sync without anyone editing a list.
RESERVE_FLAGS = frozenset({"IR", "PUP", "NA", "DNR", "Sus"})

# The rest are week to week: Out, Doubtful, Questionable. A player out
# this Sunday is still worth drafting in August, which is the half of the
# owner's rule that says "leave".
WEEKLY_FLAGS = OUT_FLAGS - RESERVE_FLAGS


def is_reserve(status: str | None) -> bool:
    """Whether this flag takes a player off the draft board."""
    return (status or "").strip() in RESERVE_FLAGS


def injury_tier(status: str | None) -> str:
    """ "out", "questionable", or "" for a player with no flag at all.

    An unrecognised value counts as questionable rather than as nothing:
    Sleeper can add one, and a flag we cannot classify is still a flag.
    Silently dropping it would be the more confident mistake.
    """
    flag = (status or "").strip()
    if not flag:
        return ""
    return "out" if flag in OUT_FLAGS else "questionable"


PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
FANTASY_POSITIONS = {"QB", "RB", "WR", "TE", "K"}
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

# IDP: both of the owner's leagues start 8 defensive players
# (docs/LEAGUES.md), so defenders belong in the index -- tagged in the
# wire, visible to the boards -- grouped the way the leagues group them.
# Sleeper's coarse `fantasy_positions` (DB/LB/DL) is preferred; the
# specific-position map is the fallback when it is absent.
IDP_GROUPS = {"DB", "LB", "DL"}
_IDP_BY_POSITION = {
    "CB": "DB",
    "S": "DB",
    "FS": "DB",
    "SS": "DB",
    "DB": "DB",
    "LB": "LB",
    "ILB": "LB",
    "OLB": "LB",
    "MLB": "LB",
    "DE": "DL",
    "DT": "DL",
    "NT": "DL",
    "DL": "DL",
    "EDGE": "DL",
}


def idp_group(rec: dict) -> str | None:
    """The DB/LB/DL group for a raw Sleeper record, or None for offense."""
    for fp in rec.get("fantasy_positions") or []:
        if fp in IDP_GROUPS:
            return fp
    return _IDP_BY_POSITION.get(rec.get("position") or "")


# Bump when the index shape changes; stale cached indexes are refetched.
# v3: defenders join the index with an `idp` group field.
# v4: team defenses join it with a `dst` flag.
# v5: a name two active players share goes to the higher-ranked one rather
#     than to whoever Sleeper serialised last, and `shared_names` records
#     which names were contested. The bump is the point: without it the
#     stored index keeps its dump-order answers for up to 20 hours, and the
#     owner keeps seeing the wrong Josh Allen after the fix has shipped.
INDEX_VERSION = 5

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
    # Sleeper's fantasy search rank: 1 = most relevant. Popularity leaks in
    # (retired stars rank well), so it is a weight, never a filter by itself.
    rank: int | None = None
    # DB/LB/DL for defenders, absent for offense -- how the owner's leagues
    # slot them (docs/LEAGUES.md).
    idp: str | None = None
    # Sleeper's own depth chart and practice report, verified live Sep 5
    # (probe run 31: depth_chart_order, depth_chart_position,
    # practice_participation, practice_description and injury_notes are on
    # 12,194 of 12,226 players). Until then the app DERIVED a depth chart
    # from last season's measured touches, which cannot see a rookie, a
    # trade or a camp battle -- the owner's question "where do we pull
    # starting depth charts from" had the honest answer "nowhere". These
    # are Sleeper's, carried as-is; None when Sleeper has nothing.
    depth_order: int | None = None
    depth_position: str | None = None
    practice: str | None = None
    practice_note: str | None = None
    injury_note: str | None = None

    def to_dict(self) -> dict:
        out = {
            "id": self.id,
            "name": self.name,
            "position": self.position,
            "team": self.team,
            "injury_status": self.injury_status,
            "rank": self.rank,
        }
        if self.idp:
            out["idp"] = self.idp
        # Present only when Sleeper has them: an absent key is "Sleeper
        # says nothing", which every reader must render as silence.
        if self.depth_order is not None:
            out["depth_order"] = self.depth_order
        if self.depth_position:
            out["depth_position"] = self.depth_position
        if self.practice:
            out["practice"] = self.practice
        if self.practice_note:
            out["practice_note"] = self.practice_note
        if self.injury_note:
            out["injury_note"] = self.injury_note
        return out


# Apostrophe variants publishers actually ship. NFKD does not fold these
# to ASCII, so without this "Ja'Marr Chase" and "Ja’Marr Chase" are two
# different players -- found Aug 21 when two real cheat sheets used
# different quotes and WR1 failed to join between them.
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "`": "'"})


def normalize(text: str) -> str:
    """Fold accents and lowercase. 'Amon-Ra St. Brown' -> 'amon ra st brown'."""
    folded = unicodedata.normalize("NFKD", text.translate(_APOSTROPHES))
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return folded.lower().replace("-", " ").replace(".", " ")


def match_key(name: str) -> str:
    """Normalized join key. 'Marvin Harrison Jr.' -> 'marvin harrison'.

    THE way two spellings of a player are matched, kernel because three
    units need the same answer: `board` keys its injected maps with it,
    `ranklists` joins rank lists on it, and `scorecard` joins graded box
    scores on it. It folds what publishers actually disagree on -- curly
    vs straight apostrophes, accents, punctuation, and the Jr/III
    suffixes -- which raw string equality does not. The scorecard's
    grader had its own weaker copy that kept the curly apostrophe, so a
    lean recorded for Ja'Marr Chase could never settle: two copies is
    how one of them stays broken.
    """
    tokens = [t for t in normalize(name or "").split() if t]
    while len(tokens) > 2 and tokens[-1] in SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(normalize(text))


def _cased_tokens(text: str) -> list[tuple[str, bool]]:
    """(normalized_token, was_capitalised) pairs, preserving order.

    Case is the cheapest available signal against common-word surnames:
    "sources heard" is lowercase, "Braylon Heard" is not.
    """
    raw = _WORD_RE.findall(text.replace("-", " ").replace(".", " "))
    return [(normalize(tok), tok[:1].isupper()) for tok in raw]


def _claim(
    keys: dict[str, str],
    key: str,
    pid: str,
    players: dict[str, dict],
    shared: set[str],
) -> None:
    """Give a name key to the player who best deserves it.

    Two active players share a name more often than is comfortable --
    Josh Allen is a Buffalo quarterback and a Jacksonville linebacker,
    Lamar Jackson a Baltimore quarterback and a corner. A plain
    `keys[key] = pid` let whichever came last in Sleeper's dump win,
    which is not a rule, and it is why the owner's sleepers list showed
    the wrong man's team and the wrong man's wire.

    The tie-break is Sleeper's own `search_rank`: lower is more
    fantasy-relevant, so the quarterback (12) beats the linebacker (240).
    An unranked player never takes a key from a ranked one. Two unranked
    players fall back to the lower id -- arbitrary, but *stable*, so two
    renders of the same dump agree with each other, which dump order did
    not guarantee either.

    This does not make an ambiguous name unambiguous; it makes the answer
    defensible and repeatable. The surname map below refuses ambiguity
    outright, and cannot here: dropping "josh allen" would cost the
    quarterback his own name to spare the linebacker.
    """
    held = keys.get(key)
    if held is None:
        keys[key] = pid
        return
    shared.add(key)
    if _rank_of(players, pid) < _rank_of(players, held):
        keys[key] = pid


def _rank_of(players: dict[str, dict], pid: str) -> tuple[int, str]:
    """Sort key: ranked before unranked, then by id so ties are stable."""
    rank = (players.get(pid) or {}).get("rank")
    return (rank if isinstance(rank, int) else 10**9, pid)


def build_index(raw: dict) -> dict:
    """Reduce Sleeper's dump to what matching needs.

    Returns {"by_name": {key: player_ID}, "players": {id: player_dict}} where
    key is a space-joined normalized name. Ambiguous surnames are excluded
    rather than resolved arbitrarily.

    **`by_name` maps to an ID, not to a record.** This docstring said
    "player_dict" until Aug 26 and two callers believed it -- one of them
    shipped, raising AttributeError on the first real page render and
    taking the Team-intel usage read down with it through a shared
    `except Exception`. Look a name up here, then read the record out of
    `players`. `tests/test_players.py` pins the shape so a third caller
    cannot make the same read.
    """
    players: dict[str, dict] = {}
    full_keys: dict[str, str] = {}
    # Names more than one active player answers to. Counted rather than
    # hidden: the resolution is a rule now, but it is still a guess about
    # which man somebody meant.
    shared_names: set[str] = set()
    surname_hits: dict[str, set[str]] = {}

    for pid, rec in raw.items():
        if not rec.get("active"):
            continue
        position = rec.get("position")

        # Team defenses (owner request, Aug 21: "some leagues do Team DEF
        # not just IDP"). Sleeper stores them keyed by team code with no
        # `full_name` and no `search_rank` -- verified live, probe run 8
        # -- which is exactly why they have never been in this index.
        #
        # They join `players` and NOTHING else on purpose. The name maps
        # drive news tagging, and "Detroit Lions" in a headline is a
        # story about a team, not a mention of a draftable asset; adding
        # it would retag the wire. Every existing consumer filters on
        # `rank is not None` or on the `idp` group, so both skip these.
        if position == "DEF":
            city = (rec.get("first_name") or "").strip()
            club = (rec.get("last_name") or "").strip()
            code = rec.get("team") or pid
            if not (city or club):
                continue
            players[pid] = Player(
                id=pid,
                name=f"{city} {club}".strip(),
                position="DEF",
                team=code,
                injury_status=None,
                rank=None,
            ).to_dict()
            players[pid]["dst"] = True
            continue

        name = rec.get("full_name") or ""
        if not name:
            continue

        # Defenders are indexed too -- both leagues start 8 of them
        # (docs/LEAGUES.md) -- carrying their coarse DB/LB/DL group.
        group = idp_group(rec) if position not in FANTASY_POSITIONS else None

        # Ambiguity is judged across EVERY active player, not just indexed
        # positions -- otherwise "adding Arnold" resolves to Dan Arnold (TE)
        # when the story is about a punter the index never saw. Non-indexed
        # players poison the surname, by design.
        if position not in FANTASY_POSITIONS and group is None:
            surname = [p for p in _tokens(name) if p not in SUFFIXES]
            if surname:
                surname_hits.setdefault(surname[-1], set()).add(pid)
            continue

        raw_rank = rec.get("search_rank")
        depth_order = rec.get("depth_chart_order")
        player = Player(
            id=pid,
            name=name,
            position=position,
            team=rec.get("team"),
            injury_status=rec.get("injury_status"),
            # Sleeper uses 9999999 for "effectively unranked".
            rank=raw_rank if isinstance(raw_rank, int) and raw_rank < 9999999 else None,
            idp=group,
            depth_order=depth_order if isinstance(depth_order, int) else None,
            depth_position=(rec.get("depth_chart_position") or None),
            practice=(rec.get("practice_participation") or None),
            practice_note=(rec.get("practice_description") or None),
            injury_note=(rec.get("injury_notes") or None),
        ).to_dict()
        players[pid] = player

        parts = _tokens(name)
        if not parts:
            continue

        # Index the full name, and the name minus any suffix, so "James Pearce"
        # matches a record stored as "James Pearce Jr.".
        #
        # `_claim`, not assignment: two ACTIVE players really do share a
        # name, and a plain overwrite let Sleeper's dump order pick the
        # winner. "Josh Allen" resolved to Jacksonville's linebacker
        # rather than Buffalo's quarterback -- reported by the owner
        # against the sleepers list, but it reached every by_name
        # consumer, news tagging included.
        _claim(full_keys, " ".join(parts), pid, players, shared_names)
        stripped = [p for p in parts if p not in SUFFIXES]
        if stripped and stripped != parts:
            _claim(full_keys, " ".join(stripped), pid, players, shared_names)

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

    return {
        "v": INDEX_VERSION,
        # When this dump was reduced. The index is the one feed that used
        # to vanish on a failed refetch instead of carrying forward, so it
        # now survives -- and a surviving copy has to be able to say how
        # old it is (Aug 22, docs/GAP_REVIEW.md).
        "fetched_at": datetime.now(UTC).isoformat(),
        "by_name": by_name,
        "surnames": surnames,
        # How many names more than one active player answers to. The
        # winner is picked by rank rather than dump order, but the reader
        # still deserves to know the question was ambiguous.
        "shared_names": sorted(shared_names),
        "players": players,
    }


# How old the index may be before the sync tries to replace it. Not an
# expiry: past this it is refetched, and if that fetch fails the previous
# copy is kept and labelled rather than dropped.
FRESH_SECONDS = 20 * 60 * 60


def fetched_at(index: dict | None) -> datetime | None:
    """When this index was built, or None if it predates the stamp."""
    raw = (index or {}).get("fetched_at")
    if not raw:
        return None
    try:
        stamp = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


def age_seconds(index: dict | None, now: datetime | None = None) -> float | None:
    stamp = fetched_at(index)
    if stamp is None:
        return None
    return ((now or datetime.now(UTC)) - stamp).total_seconds()


def age_note(index: dict | None, now: datetime | None = None) -> str:
    """ " · player index Nh old", or "" when the age is unknowable.

    Every served board printed the REQUEST time and nothing else -- "checked
    Sat Aug 24, 09:41 AM Central" -- while /app/nextup went as far as "the
    flags are live". Since a failed refetch deliberately keeps the previous
    copy rather than emptying the boards, a week-old index renders
    byte-identically to a fresh one under a stamp saying it was checked this
    minute. The generation time is true and says nothing about the data.

    `age_seconds` has existed since Aug 22 and only /health read it; this is
    the same number, on the surfaces people actually look at. Appended to
    the stamp rather than replacing it, because when a page was built and
    how old its data is are two different facts and both are worth having.
    """
    age = age_seconds(index, now)
    if age is None:
        return ""
    return f" \u00b7 player index {age / 3600:.1f}h old"


def needs_refresh(index: dict | None, now: datetime | None = None) -> bool:
    """Whether the sync should try for a newer copy.

    Missing, wrong-version, or unstamped all count -- an unstamped index
    predates this scheme and its age cannot be judged, so it is treated as
    due rather than trusted.
    """
    if not index or not index.get("players"):
        return True
    age = age_seconds(index, now)
    return age is None or age > FRESH_SECONDS


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
    """Attach a `players` list to each item. Mutates and returns the list.

    Items that arrive pre-seeded (Rotoworld names its player structurally,
    which beats matching the headline text) are enriched with the index's
    id and rank when the player is known -- never clobbered.
    """
    by_name = index.get("by_name", {})
    players = index.get("players", {})
    for item in items:
        seeded = item.get("players")
        if seeded:
            for entry in seeded:
                # Join-split, not strip: "C.J. Stroud" normalizes with a
                # double space, and by_name keys are single-spaced -- the
                # bare strip() missed every dotted or initialed name.
                pid = by_name.get(" ".join(normalize(entry.get("name", "")).split()))
                if pid and pid in players:
                    known = players[pid]
                    entry["id"] = pid
                    entry["rank"] = known.get("rank")
                    entry.setdefault("position", known.get("position"))
                    entry["team"] = entry.get("team") or known.get("team")
            continue
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
    log.info(
        "player index: %d players, %d name keys, %d names shared by two actives",
        len(index["players"]),
        len(index["by_name"]),
        len(index.get("shared_names") or []),
    )
    return index
