# League settings — a user's own league, their own numbers

Owner request, Aug 21: *"we should also add the ability to adjust league
setting for users."*

Everything this app says about a player is downstream of scoring. An IDP
board at 4 points a sack is a different board from one at 2. Telling
someone to reach for a quarterback is only true if their league actually
pays for one. Two built-in leagues — the owner's, verified from their own
Yahoo settings pages — are exactly right for the owner and useless to
anyone else. `/app/leagues` is where a signed-in user describes theirs.

## What a user can change

**Everything**, deliberately — not a preset list. A preset is a promise
that everyone's league is one of N shapes; the moment someone's isn't,
the app is confidently wrong about their draft, which is the one failure
this repo will not ship (the no-false-positives rule in CLAUDE.md).

- **Size** — 4 to 20 teams
- **Starting lineup and bench** — counts per slot, including `FLX` (any
  WR/RB/TE), `D` (any defender the league starts), and `BN`
- **Offense scoring** — per reception, passing TD, pass yards per point,
  per completion, receiving yards per point, rush yards per point
- **IDP** — the ten per-event values (solo, assist, sack, INT, FF, FR,
  defensive TD, safety, pass defensed, blocked kick) plus the
  turnover-return-yardage divisor

## What the app derives, and shows you deriving

The editor prints its own reading back, because the point is to watch the
advice change rather than take it on faith:

| Derived | From | Why it is not a separate setting |
|---|---|---|
| Startable defensive groups | the slots | A league with no DL slot can never be told it has one |
| FFC ADP column (10- or 12-team) | the room size | The board a draft is actually priced against |
| QB premium, in points per game | pass TD, yards/point, per completion, measured against a stated market baseline (4-pt TD, 25 yds/pt, 0/completion) | So "QBs go early here" is a measurement, never an assertion |
| QB draft-slot boost | that premium | Capped at two rounds — the translation is crude at the extremes |
| Rounds | total roster spots | |

Two rules about the QB boost that are worth stating plainly:

- The **built-ins keep tuned values** (NDDPL 10, RED_EYE 18). Those came
  from how those specific rooms actually draft, not from arithmetic.
- **No user league ever inherits one.** Not a new league, not a copy of a
  built-in. A borrowed number would be a judgement about somebody else's
  room wearing this user's league name.

## Where the settings land

| Surface | What it does with them |
|---|---|
| `/app/leagues` | the editor itself |
| `/app/mock` | the room offers each league at its own size, slots, ADP column and QB boost; pick reasons quote the league's own numbers |
| `/app/idp` | one score-and-rank column per league that starts defenders; a league that starts none gets no column |

A visitor with no leagues of their own — including the watchdog, which
has no session — sees the owner's verified two, exactly as before.

## Storage

Per email, in the same Redis blob as `/app/mine`
(`fbbible:user:<email>`), as a list under `leagues`. Nobody else can see
them; there is no owner browse-other-users view, same as `/app/mine`.
Cap: 6 leagues each.

A stored league is read back through `League.from_dict`, which **ignores
anything it does not recognise** and drops a blob it cannot rebuild at
all. Stored settings outlive the code that wrote them, and a draft board
that 500s the morning of a draft is worse than one missing a league.

## Validation refuses; it does not repair

Silently clamping a league to something it isn't would make every number
downstream a quiet lie about that user's draft. So:

- teams outside 4–20 → refused, and the message says why (the mock room
  seats every team from one live player pool)
- more than 40 roster spots → refused
- no starting slots → refused
- starts defenders but scores them nothing → refused, because the
  defensive board would rank everyone at zero and present it as a ranking
- a yards-per-point of zero → refused; it is a divisor

## Code map

- `app/leagues.py` — the `League` dataclass, the built-in two, the
  market baselines, and the store-shape helpers (`user_leagues`,
  `for_user`, `slots_from_counts`)
- `app/routes/leaguecfg.py` — the editor page and its four routes
- `app/feeds/idp.py`, `app/feeds/mock.py` — consumers; both take
  `board_leagues` and default to the built-ins
- `tests/test_leagues.py`, `tests/test_leaguecfg.py` — the contract
- `tests/test_mock_engine.py` — drives the room's JavaScript under node,
  so a league-config change that breaks the draft fails in CI

## Not covered yet

- **The main app page** (`/app/`) still renders the owner's two leagues in
  its own picker — that is design-document markup renamed at serve time,
  not something the League dataclass reaches yet.
- **The printable cheat sheet** (`/app/cheatsheet`) is ADP-first and
  carries the owner's league caveat as prose.
- **Kicker and team-defense scoring** are not modelled anywhere in the
  app, so they are not in the editor either. Adding fields nothing reads
  would be a false promise.
