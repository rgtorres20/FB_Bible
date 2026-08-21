"""One canonical description of a league, for every surface that scores.

Until now the same facts lived twice: Python dicts in `feeds/idp.py` and
a JavaScript object inside `feeds/mock.py`. They agreed because someone
kept them agreeing. That is fine for two leagues the owner verified by
hand and impossible for leagues a user defines, so this module is the
single shape both derive from.

The two verified leagues (docs/LEAGUES.md, from the owner's own Yahoo
settings pages) ship as the built-in defaults. A user-defined league is
the same dataclass with different numbers -- nothing about the scoring
path knows the difference.

Market baselines are stated rather than assumed: standard fantasy scores
a 4-point passing TD at 25 yards per point and nothing per completion.
Everything this app says about a league being "QB-premium" is measured
against those three numbers, so a league that matches the market gets no
adjustment rather than an invented one.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

# What "the market" means -- the scoring ADP is built on.
MARKET_PASS_TD = 4.0
MARKET_PASS_YDS_PER_PT = 25.0
MARKET_PASS_COMPLETION = 0.0
MARKET_REC_YDS_PER_PT = 10.0

# Rough per-game volume for a starting QB, used only to turn a scoring
# difference into a draft-board adjustment. A heuristic, labelled as one.
QB_TD_PER_GAME = 1.6
QB_PASS_YDS_PER_GAME = 250.0
QB_COMPLETIONS_PER_GAME = 22.0
# Points-per-game premium worth roughly one round of draft capital in a
# 10-12 team room. A heuristic, and the shakiest number here: a premium
# every quarterback receives equally lifts the whole position rather than
# spreading it, so the translation into draft slots saturates. Hence the
# cap below -- without it RED_EYE's point-per-completion scoring derives
# a 110-slot boost, which would put every QB in the first round.
POINTS_PER_ROUND = 3.0
MAX_DERIVED_QB_BOOST = 24.0

IDP_GROUPS = ("DB", "LB", "DL")


@dataclass(frozen=True)
class League:
    """Everything the app needs to score and draft one league."""

    key: str
    name: str
    teams: int
    # Starting slots plus bench, in draft-priority order. "FLX" is any of
    # WR/RB/TE; "D" is any IDP group the league starts.
    slots: tuple[str, ...]
    # Offense, as the league's own settings page states it.
    ppr: float = 1.0
    pass_td: float = MARKET_PASS_TD
    pass_yds_per_pt: float = MARKET_PASS_YDS_PER_PT
    pass_completion: float = MARKET_PASS_COMPLETION
    rec_yds_per_pt: float = MARKET_REC_YDS_PER_PT
    rush_yds_per_pt: float = 10.0
    # IDP, keyed by the Sleeper stat fields (verified via the probe's
    # field census before any of them were trusted).
    idp: dict[str, float] = field(default_factory=dict)
    idp_ret_yds_per_pt: float = 20.0
    # How far up the board the mock room moves this league's QBs. None
    # derives it from the scoring above; the two verified leagues carry
    # values tuned against real draft behaviour instead.
    qb_boost_override: float | None = None

    @property
    def idp_groups(self) -> frozenset[str]:
        """Which defensive groups this league can actually start.

        Derived from the slots rather than configured separately, so a
        league with no DL slot can never be told it has one. A generic
        "D" slot admits every group.
        """
        if "D" in self.slots:
            return frozenset(IDP_GROUPS)
        return frozenset(g for g in IDP_GROUPS if g in self.slots)

    @property
    def starts_idp(self) -> bool:
        return bool(self.idp_groups)

    @property
    def rounds(self) -> int:
        return len(self.slots)

    @property
    def adp_size_key(self) -> str:
        """Which FantasyFootballCalculator column this league drafts
        against -- its own size, rounded to the two FFC publishes."""
        return "a12" if self.teams >= 11 else "a10"

    @property
    def qb_premium_per_game(self) -> float:
        """Points per game a starting QB scores here above the market.

        Measured, not asserted: this is what justifies telling someone to
        draft QBs earlier than ADP, so it has to fall out of their actual
        settings. A league matching the market returns 0.0.
        """
        td = (self.pass_td - MARKET_PASS_TD) * QB_TD_PER_GAME
        yards = QB_PASS_YDS_PER_GAME * (1 / self.pass_yds_per_pt - 1 / MARKET_PASS_YDS_PER_PT)
        completions = (self.pass_completion - MARKET_PASS_COMPLETION) * QB_COMPLETIONS_PER_GAME
        return round(td + yards + completions, 2)

    @property
    def qb_draft_boost(self) -> float:
        """The QB premium expressed as draft slots, for the mock room.

        An explicit override wins, because the two verified leagues were
        tuned against how their rooms actually draft. Otherwise derive
        and cap: the derivation is directionally right and numerically
        crude, so it is not allowed to produce a boost larger than two
        rounds however extreme the scoring gets.
        """
        if self.qb_boost_override is not None:
            return self.qb_boost_override
        derived = self.qb_premium_per_game / POINTS_PER_ROUND * self.teams
        return round(min(derived, MAX_DERIVED_QB_BOOST), 1)

    @property
    def receiving_is_halved(self) -> bool:
        return self.rec_yds_per_pt > MARKET_REC_YDS_PER_PT

    def score_idp(self, stats: dict) -> float:
        """One defender's season total under this league's settings."""
        points = sum(stats.get(f, 0) * v for f, v in self.idp.items())
        returns = stats.get("idp_int_ret_yd", 0) + stats.get("idp_fum_ret_yd", 0)
        if self.idp_ret_yds_per_pt:
            points += returns / self.idp_ret_yds_per_pt
        return round(points, 1)

    def to_dict(self) -> dict:
        """Plain data, for the store and for the browser."""
        return {
            "key": self.key,
            "name": self.name,
            "teams": self.teams,
            "slots": list(self.slots),
            "ppr": self.ppr,
            "pass_td": self.pass_td,
            "pass_yds_per_pt": self.pass_yds_per_pt,
            "pass_completion": self.pass_completion,
            "rec_yds_per_pt": self.rec_yds_per_pt,
            "rush_yds_per_pt": self.rush_yds_per_pt,
            "idp": dict(self.idp),
            "idp_ret_yds_per_pt": self.idp_ret_yds_per_pt,
            "qb_boost_override": self.qb_boost_override,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> League:
        """Rebuild from stored data, ignoring anything unrecognised so an
        older or hand-edited blob cannot crash the scoring path."""
        known = {f for f in cls.__dataclass_fields__ if f != "slots"}
        kwargs = {k: v for k, v in (raw or {}).items() if k in known}
        kwargs["slots"] = tuple(raw.get("slots") or ())
        kwargs.setdefault("key", "league")
        kwargs.setdefault("name", "League")
        kwargs.setdefault("teams", 10)
        return cls(**kwargs)


# --- the owner's two, verified from their Yahoo settings pages ----------

_BASE_IDP = {
    "idp_tkl_solo": 1.0,
    "idp_tkl_ast": 0.5,
    "idp_sack": 3.0,
    "idp_int": 2.0,
    "idp_ff": 2.0,
    "idp_fum_rec": 2.0,
    "idp_def_td": 6.0,
    "idp_safe": 2.0,
    "idp_pass_def": 1.0,
    "idp_blk_kick": 2.0,
}

NDDPL = League(
    key="nddpl",
    name="NDDPL",
    teams=10,
    slots=(
        "QB",
        "RB",
        "RB",
        "RB",
        "WR",
        "WR",
        "WR",
        "WR",
        "TE",
        "K",
        "DB",
        "DB",
        "DB",
        "DB",
        "LB",
        "LB",
        "LB",
        "LB",
        *(("BN",) * 8),
    ),
    pass_td=6.0,
    pass_yds_per_pt=20.0,
    rec_yds_per_pt=20.0,
    idp=dict(_BASE_IDP),
    idp_ret_yds_per_pt=20.0,
    qb_boost_override=10.0,
)

RED_EYE = League(
    key="red_eye",
    name="RED_EYE",
    teams=12,  # owner correction Aug 20, superseding the PDF's 10
    slots=(
        "QB",
        "RB",
        "RB",
        "WR",
        "WR",
        "WR",
        "TE",
        "FLX",
        "K",
        "D",
        "D",
        "D",
        "D",
        "DB",
        "DB",
        "DB",
        "DB",
        *(("BN",) * 8),
    ),
    pass_td=6.0,
    pass_yds_per_pt=20.0,
    pass_completion=1.0,
    rec_yds_per_pt=20.0,
    idp={**_BASE_IDP, "idp_sack": 2.0, "idp_int": 3.0},
    idp_ret_yds_per_pt=10.0,
    qb_boost_override=18.0,
)

DEFAULTS: tuple[League, ...] = (NDDPL, RED_EYE)


def defaults() -> list[League]:
    return list(DEFAULTS)


def blank(name: str = "My league", teams: int = 10) -> League:
    """A starting point for someone defining their own -- market scoring
    and a conventional roster, so every number they change is a
    deliberate statement about their league rather than inherited from
    somebody else's."""
    return replace(
        NDDPL,
        key="custom",
        name=name,
        teams=teams,
        slots=(
            "QB",
            "RB",
            "RB",
            "WR",
            "WR",
            "TE",
            "FLX",
            "K",
            *(("BN",) * 6),
        ),
        pass_td=MARKET_PASS_TD,
        pass_yds_per_pt=MARKET_PASS_YDS_PER_PT,
        pass_completion=MARKET_PASS_COMPLETION,
        rec_yds_per_pt=MARKET_REC_YDS_PER_PT,
        idp={},
        idp_ret_yds_per_pt=0.0,
        # Not inherited: NDDPL's boost was tuned against how that room
        # actually drafts, and applying it to somebody else's league
        # would be an invented number wearing a verified one's clothes.
        # None means "derive it from the scoring they entered".
        qb_boost_override=None,
    )
