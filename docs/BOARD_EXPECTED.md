# Draft board — expected results

**The artifact that can be wrong.** Everything else about weights so far
has been a design that cannot fail a test. This is the table the code
gets checked against, and it is written *before* the code.

The rule it exists to enforce: a weight is applied to something, that
something is the **order of the draft board**, and for each weight
setting there is an ordering we said in advance we expected. Without
that, "working" and "not running at all" look identical — which is
exactly how five sliders sat wired to nothing.

Owner to correct the numbers. I should not be choosing them.

---

## 1. The fixture — real players, real board

All rows below are the app's actual committed board (`RAW_BOARD`,
`frontend/index.html`, 205 players). The `FSB #` column is real. The rest
are **inputs to be filled from the live sources**, and are deliberately
blank rather than guessed.

| FSB # | Player | Pos | ESPN 300 | Yahoo 300 | Sleeper | FFC ADP | My tier |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 4 | Puka Nacua | WR · LAR | | | | | |
| 11 | Malik Nabers | WR · NYG | | | | | |
| 19 | Brock Bowers | TE · LV | | | | | |
| 24 | Trey McBride | TE · ARI | | | | | |
| 25 | Josh Allen | QB · BUF | | | | | |
| 32 | Jayden Daniels | QB · WSH | | | | | |
| 62 | Zaire Franklin | LB · IND | | | | **none** | |
| 81 | Kyle Hamilton | DB · BAL | | | | **none** | |
| 200 | Jake Bates | K · DET | | | | | |

Two of those `none` cells are the point of the whole exercise, and they
are measured, not assumed: **49 of the 205 players on this board are
individual defenders** (25 LB, 23 DB, 1 WR/DB). FFC's PPR ADP carries no
IDP at all. So 24% of the board has no ADP by construction — before
anyone touches a slider.

### The board is 95 players short of the draft it is used in

Owner, Aug 21: *"why only 205 players, i have you list of 300 at least"* —
correct, and it is a live defect, not a documentation gap. Measured
against `app/leagues.py`:

| Surface | Depth | Needs | |
| --- | ---: | ---: | --- |
| Mock room offense pool | 300 | 300 | OK |
| Mock room defender pool | 400 | 300 | OK |
| Top-300 alert board | 300 | 300 | OK |
| **Draft analyzer `RAW_BOARD`** | **205** | **300** | **short by 95** |
| **ADP blend `MAX_BOARD`** | **220** | **300** | **short by 80** |

*Needs* is the deepest draft this app serves: RED_EYE at 12 teams x 25
rounds = **300 picks**. NDDPL needs 260. So the draft board empties with
roughly eight rounds still to go — and it goes silent exactly when the
picks get hard and a tool is most useful. The mock room was built to 300
and the alert board to 300; the board the owner would actually draft from
is the one that was not.

### And the total was the *smaller* problem

Owner, Aug 21: *"the board should go by number of players allowed by team
and bench players that determine the size."* That is already how the
requirement is computed — `League.rounds` is `len(self.slots)`, starters
plus bench — so it is derived from the league and cannot disagree with
it. Edit a roster at `/app/leagues` and the board requirement moves.

But counting only the total hides the real gap. A board with 300 rows and
49 defenders still cannot seat a league that starts eight per team:

| League | Roster | Board needed | IDP starters needed | Board has | Short |
| --- | ---: | ---: | ---: | ---: | ---: |
| NDDPL | 18+8 = 26 | 260 | 80 | 49 | **31** |
| RED_EYE | 17+8 = 25 | 300 | 96 | 49 | **47** |
| BALLAPALOSA | 10+6 = 16 | 160 | n/a — team D/ST | — | — |

Kickers are short in all three: 6 on the board against 10–12 starters.

**RED_EYE starts 96 individual defenders across twelve teams and the
board carries 49.** Half the league cannot fill its defensive lineup from
it — a worse failure than running out in round 18, because it is wrong
from the first defensive pick rather than at the end.

BALLAPALOSA's DEF slot is a whole-team defence from `/api/defenses` (32
stored, verified live), not from this board, so it is not a shortfall.

`MAX_BOARD` is fixed (220 -> 320) with a test pinning it to
`max(teams x rounds)`. `RAW_BOARD` is **not** fixed here: it ships from
the design project, so a deeper board is a design-side change
([DESIGN_CONTRACT.md](DESIGN_CONTRACT.md)).
`tests/test_board_depth.py` holds the shortfalls as a ratchet — they can
only shrink, and a resync that ships a shallower board fails.

Board composition, counted from the committed file:

| RB | WR | TE | QB | LB | DB | WR/DB | K |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 51 | 53 | 22 | 24 | 25 | 23 | 1 | 6 |

## 2. Expected results

Each case is a sentence that can fail. Cases C–E are fully specified now
because they are structural. Cases A–B need section 1 filled in first —
stating an expected order without the inputs would be inventing one.

### Case A — weights change the order *(needs the fixture filled)*

Two settings over the same players:

| Setting | Weights | Expected order |
| --- | --- | --- |
| A1 | all lists equal | *fill after section 1* |
| A2 | ADP ×3, others ×1 | *fill after section 1* |

The assertion is not the exact list — it is that **A1 and A2 differ, in a
direction the owner named in advance.** A weight setting that changes
nothing is the bug this whole thread is about.

### Case B — QB premium *(needs the fixture filled)*

NDDPL and RED_EYE both score QBs above market (6-pt passing TDs, 20
yds/pt; RED_EYE adds 1/completion — docs/LEAGUES.md). So:

> With league scoring applied, Josh Allen ranks **above** his market ADP
> position, and the gap is larger in RED_EYE than in NDDPL.

### Case C — "My tiers only" keeps a usable board ✅ *specifiable now*

The escape hatch survives (docs/WEIGHTS.md decision 4), so:

> With every market list at weight 0 and only my tiers active, **all 205
> players still have a defined position on the board**, and every player
> my tiers never ranked is shown as *"unranked by your sources"* rather
> than sorted to the bottom as though he were bad.

This is the case the N-list model would break if written naively. Under
the old two-list blend a missing ADP fell back to `b.rank`, so there was
always a number; renormalizing over present lists leaves a player ranked
by zero active lists undefined. At "my tiers only" that is every one of
the 6 kickers and 49 defenders the owner never personally ranked, plus
most of the tail.

### Case D — a dead control changes nothing ✅ *specifiable now*

The regression test for the original defect:

> Moving any **News wires** slider produces a byte-identical board.

If that ever fails, a wire weight has silently acquired influence over
the draft board, which no decision authorised. And note the panel already
says these are `not wired` — so this test also keeps the *label* honest.

### Case E — ADP is not in the blend ✅ *specifiable now*

Decision 4 pulled ADP out of the rank aggregation and made it an
availability column:

> Changing any board-trust weight changes the **order**, and leaves every
> player's **ADP / availability** value untouched.

Rank answers "who is better". ADP answers "when will he be gone". A
change to the first must not move the second.

## 3. Filling section 1

The four market columns are not reachable from the dev container — FFC
returns nothing and the deployment is blocked by egress. They have to
come from a runner or from the owner:

- **FFC ADP** — the live board already carries it; it is injected into
  the served page as `FB_LIVE_ADP` (see `app/feeds/board.py`). A runner
  fetching `/app/` can read it out.
- **Sleeper search_rank** — in the stored player index.
- **ESPN top-300 / Yahoo top-300** — imported artefacts, owner-supplied.
- **My tier** — only the owner has this, by definition.

Fill what is available, leave the rest blank, and mark blanks as blank.
A guessed number here would defeat the purpose of the document.
