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
- **Team defense (D/ST)** — for a `DEF` slot: eight per-event values, the
  seven-band points-allowed ladder, and (folded away, because almost
  nobody scores it) the nine-band yards-allowed ladder

`DEF` and `D` are different slots. `DEF` is a whole team's defense and
special teams scored as one unit; `D` is one more individual defender of
any group the league starts. Owner, Aug 21: *"some leagues do Team DEF
not just IDP"* — and, *"if DEF is chosen IDP can't be used."* **A league
uses one or the other**, and the editor refuses a roster with both: it
would need two rankings for one lineup decision, and the boards would
show a defender and a whole defense competing for slots that are not
interchangeable.

## What the app derives, and shows you deriving

The editor prints its own reading back, because the point is to watch the
advice change rather than take it on faith:

| Derived | From | Why it is not a separate setting |
|---|---|---|
| Startable defensive groups | the slots | A league with no DL slot can never be told it has one |
| Whether team defenses are drafted at all | a `DEF` slot in the roster | A league that starts none is never shown a D/ST ranking |
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
| `/app/idp` | one score-and-rank column per league that starts defenders; a league that starts none gets no column. A **Team defenses** table sits above it for leagues with a `DEF` slot, again one column each. A league whose only defensive slot is `DEF` gets that table and no IDP board at all |

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
- starts a `DEF` slot but scores it nothing → refused, because all 32
  defenses would rank identically at zero and a flat list presented as a
  ranking is the same false positive
- starts both a `DEF` slot and individual defenders → refused (owner's
  rule, above)

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

## Where the team-defense numbers come from

Sleeper's season dump holds three populations in one dict: ~8,200 numeric
player keys, 32 `TEAM_XXX` offense keys, and 32 **bare team codes** that
carry the team defense / special-teams aggregates. That third population
was counted and discarded until Aug 21. Two traps were found by probing
it (`Actions → Probe endpoint → url + key=DET`) rather than assuming:

- The entry carries a bare **`td`**, which on Detroit reads **57** —
  touchdowns *allowed*. Pricing it as a defensive touchdown would have
  handed every defense several hundred phantom points. `def_st_td` is the
  score, and it already counts both defensive and return touchdowns, so
  the separately-stored `def_td` and `st_td` must not be added alongside.
- **`sack`, `int`, `ff`, `fum_rec`, `td`, `qb_hit` each have 64 holders,
  not 32** — the team *offense* entries use the same names for sacks and
  turnovers *given up*. The extractor reads the bare team codes and
  nothing else.

Two more shapes the settings pages force:

- Yahoo asks for one **"Block Kick"** number; Sleeper splits blocked
  field goals, punts and extra points across three fields. The reducer
  sums them into `blk_kick_any` so the editor keeps asking the one
  question the settings page asks.
- **4th-down stops** are a Yahoo default of 0 and BALLAPALOSA pays **5**.
  At five points a stop, leaving the field out would understate a good
  defense by fifty-odd points a season, so it is in.

The points-allowed ladder needs no reconstruction: Sleeper already stores
how many games each defense finished inside each band, at exactly the
boundaries Yahoo and ESPN use, so a season total is a dot product. The
reducer **checks** that: a defense's bands must account for all of its
games, and `coverage.defense_pa_complete` counts how many do. The board
renders only when every stored defense passes, because ranking off a
partial ladder would silently underscore whichever defense is missing a
band — and an underscored defense reads as a ranking, not as a gap.

`GET /api/defenses` returns the stored lines unscored, plus that count.
Unscored on purpose: what a defense is worth depends entirely on the
league reading it. The watchdog checks it, since the D/ST board itself is
only visible to a signed-in user whose league has a `DEF` slot.

## Not covered yet

- **The main app page** (`/app/`) still renders the owner's two leagues in
  its own picker — that is design-document markup renamed at serve time,
  not something the League dataclass reaches yet.
- **The printable cheat sheet** (`/app/cheatsheet`) is ADP-first and
  carries the owner's league caveat as prose.
- **Kicker scoring** is not modelled anywhere in the app, so it is not in
  the editor either. Adding fields nothing reads would be a false
  promise. (Team defense *is* modelled now — see above.)
- **D/ST kick and punt return yardage.** Stored (`def_kr_yd`,
  `def_pr_yd`) but not scored: most leagues credit those to the returner,
  not the defense. The board says so rather than quietly leaving them
  out. Turnover-return yardage (`int_ret_yd` + `fum_ret_yd`) *is*
  scorable, via the same divisor the IDP side uses.
- **D/ST three-and-outs and forced punts.** Stored by Sleeper
  (`def_3_and_out`, `def_forced_punts`), scored by a small minority of
  leagues, not in the editor. (4th-down stops *are* in — BALLAPALOSA
  pays 5 apiece.)
- **"Extra point returned."** BALLAPALOSA scores it 2. Sleeper's
  `def_2pt` has only two holders across the whole dump, so which
  population it belongs to was not verifiable from the census alone and
  it is left out rather than guessed. Worth at most a couple of points a
  season.
- **Offense bonus thresholds** (4 pts at 400 passing yards, 4 at 175
  rushing/receiving, 40+ yard TD bonuses) and the non-yardage offense
  categories (INT, fumbles lost, 2-pt). The offense half of a League only
  drives the QB premium and the ADP column — player ranks come from
  market ADP — so these change nothing the app computes today.
