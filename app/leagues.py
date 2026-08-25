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

import logging
from dataclasses import dataclass, field, replace

_log = logging.getLogger(__name__)

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
# 10-12 team room. A heuristic, and still the shakiest number here.
#
# The cap below used to be load-bearing: the derivation counted the
# point-per-completion bonus, which every starting QB earns equally, and
# RED_EYE derived a 110-slot boost that would have put every quarterback
# in the first round. `qb_spread_premium_per_game` excludes that class of
# bonus now, so the cap is a backstop rather than the thing doing the
# work.
POINTS_PER_ROUND = 3.0
MAX_DERIVED_QB_BOOST = 24.0

IDP_GROUPS = ("DB", "LB", "DL")

# Roster slots, in the order a lineup card reads them. A league is
# defined by how many of each it starts; this order is what turns those
# counts back into the slot tuple. "FLX" is any of WR/RB/TE, "DEF" is a
# whole team defense/special teams, "D" is any individual defender the
# league starts, and "BN" is bench. DEF and D are different things and
# a league can start both -- the owner request that added DEF ("some
# leagues do Team DEF not just IDP") is exactly that distinction.
SLOT_ORDER = ("QB", "RB", "WR", "TE", "FLX", "K", "DEF", "DL", "LB", "DB", "D", "BN")

# The IDP events a league can price, with the label the editor shows.
# Keyed by the Sleeper stat fields -- every one verified against the live
# dump's field census before it was trusted (probe run 5, 2026-08-20).
IDP_FIELDS: tuple[tuple[str, str], ...] = (
    ("idp_tkl_solo", "Solo tackle"),
    ("idp_tkl_ast", "Assisted tackle"),
    ("idp_sack", "Sack"),
    ("idp_int", "Interception"),
    ("idp_ff", "Forced fumble"),
    ("idp_fum_rec", "Fumble recovery"),
    ("idp_def_td", "Defensive TD"),
    ("idp_safe", "Safety"),
    ("idp_pass_def", "Pass defensed"),
    ("idp_blk_kick", "Blocked kick"),
)

# Team defense / special teams, keyed by the fields Sleeper's season dump
# carries on its bare team-code entries -- verified live before any of
# them were trusted (probe run 7, 2026-08-21: DET holds all of these).
#
# Two traps in that entry, both found by looking rather than guessing:
#
#   * a bare `td`, which on Detroit reads 57 -- touchdowns *allowed*,
#     not scored. Pricing it as a defensive touchdown would have handed
#     every defense several hundred phantom points.
#   * `sack`, `int`, `ff`, `fum_rec`, `td` and `qb_hit` each have 64
#     holders across the dump, not 32: the team OFFENSE entries carry
#     the same names for sacks and turnovers *given up*. Only the bare
#     team-code entries are defenses, which is why the extractor reads
#     those keys and no others.
#
# `def_st_td` is the touchdown field: defense plus return, which is what
# a Yahoo D/ST touchdown category counts. The dump also carries `def_td`
# and `st_td` separately, so adding them alongside it would double-count.
DST_FIELDS: tuple[tuple[str, str], ...] = (
    ("sack", "Sack"),
    ("int", "Interception"),
    ("ff", "Forced fumble"),
    ("fum_rec", "Fumble recovery"),
    ("def_st_td", "Defensive / return TD"),
    ("safe", "Safety"),
    # Yahoo asks for one "Block Kick" number; Sleeper splits blocked
    # field goals, punts and extra points across three fields. The
    # reducer sums them into `blk_kick_any` so the editor can keep asking
    # the one question the settings page asks.
    ("blk_kick_any", "Blocked kick"),
    # Scored at 5 in BALLAPALOSA and 0 by Yahoo default, which is exactly
    # why it is here: at 5 points a stop, leaving it out would understate
    # a good defense by fifty-odd points a season.
    ("def_4_and_stop", "4th-down stop"),
    ("def_pass_def", "Pass defensed"),
)

# The points-allowed ladder. Yahoo and ESPN both use these boundaries and
# Sleeper's dump already buckets each team's games into them, so a season
# total is a dot product rather than a reconstruction: the stored value is
# how many games the team held an opponent inside that band.
DST_PA_TIERS: tuple[tuple[str, str], ...] = (
    ("pts_allow_0", "Shutout"),
    ("pts_allow_1_6", "1–6 allowed"),
    ("pts_allow_7_13", "7–13 allowed"),
    ("pts_allow_14_20", "14–20 allowed"),
    ("pts_allow_21_27", "21–27 allowed"),
    ("pts_allow_28_34", "28–34 allowed"),
    ("pts_allow_35p", "35+ allowed"),
)

# The yards-allowed ladder, same idea, at Sleeper's own boundaries.
# Offered because some Yahoo leagues really do score it and refusing
# would be the preset mistake in miniature -- but almost every league
# leaves these at zero, so the editor keeps them folded away.
DST_YA_TIERS: tuple[tuple[str, str], ...] = (
    ("yds_allow_0_100", "Under 100 allowed"),
    ("yds_allow_100_199", "100–199 allowed"),
    ("yds_allow_200_299", "200–299 allowed"),
    ("yds_allow_300_349", "300–349 allowed"),
    ("yds_allow_350_399", "350–399 allowed"),
    ("yds_allow_400_449", "400–449 allowed"),
    ("yds_allow_450_499", "450–499 allowed"),
    ("yds_allow_500_549", "500–549 allowed"),
    ("yds_allow_550p", "550+ allowed"),
)

# Yahoo's own D/ST defaults, offered as the starting point when someone
# adds a DEF slot -- the numbers most leagues never change.
DEFAULT_DST = {
    "sack": 1.0,
    "int": 2.0,
    "ff": 0.0,
    "fum_rec": 2.0,
    "def_st_td": 6.0,
    "safe": 2.0,
    "blk_kick_any": 2.0,
    "def_4_and_stop": 0.0,
    "def_pass_def": 0.0,
}
DEFAULT_DST_PA = {
    "pts_allow_0": 10.0,
    "pts_allow_1_6": 7.0,
    "pts_allow_7_13": 4.0,
    "pts_allow_14_20": 1.0,
    "pts_allow_21_27": 0.0,
    "pts_allow_28_34": -1.0,
    "pts_allow_35p": -4.0,
}

# Bounds the editor enforces. Not arbitrary: the mock room seats every
# team from one live player pool, so a 40-team league would simply run
# the pool dry mid-draft and a 60-round one would draft kickers to the
# bench. Refusing is honest; drafting air is not.
MIN_TEAMS = 4
MAX_TEAMS = 20
MAX_ROUNDS = 40


@dataclass(frozen=True)
class League:
    """Everything the app needs to score and draft one league."""

    key: str
    name: str
    teams: int
    # Starting slots plus bench, in draft-priority order. "FLX" is any of
    # WR/RB/TE; "D" is any IDP group the league starts.
    slots: tuple[str, ...]
    # The league's id on Yahoo, for deep links. Here rather than in the
    # page because league facts live in this module and nowhere else --
    # the page held these, and that is exactly how a third league ended
    # up missing from half the surfaces that name leagues (Aug 25).
    # Empty for a league somebody defined by hand: no id, so no link.
    yahoo_id: str = ""
    # Offense, as the league's own settings page states it.
    ppr: float = 1.0
    pass_td: float = MARKET_PASS_TD
    pass_yds_per_pt: float = MARKET_PASS_YDS_PER_PT
    pass_completion: float = MARKET_PASS_COMPLETION
    rec_yds_per_pt: float = MARKET_REC_YDS_PER_PT
    rush_yds_per_pt: float = 10.0
    # Added Aug 21 with the offense scorer. Every value is the owner's
    # verified Yahoo setting (docs/LEAGUES.md) -- all three leagues agree
    # on these four, which is why they are plain defaults rather than
    # per-league overrides.
    rush_td: float = 6.0
    rec_td: float = 6.0
    pass_int: float = -2.0
    fum_lost: float = -2.0
    two_pt: float = 2.0
    # Kickers. Distance tiers are a Yahoo setting this repo has not
    # verified per league, so a made field goal is scored flat and the
    # scorer says so rather than guessing 3/4/5 by yardage.
    fg_made: float = 3.0
    xp_made: float = 1.0
    # Kick and punt returns, the "returners score" rule both IDP leagues
    # carry (docs/LEAGUES.md: 20 yds/pt, return TD 6, Yahoo default 0).
    # Zero here means the league does not pay them, which is the market
    # default a blank league starts from.
    ret_yds_per_pt: float = 0.0
    ret_td: float = 0.0
    # IDP, keyed by the Sleeper stat fields (verified via the probe's
    # field census before any of them were trusted).
    idp: dict[str, float] = field(default_factory=dict)
    idp_ret_yds_per_pt: float = 20.0
    # Team defense / special teams, for leagues that start a DEF slot
    # instead of (or alongside) individual defenders. Per-event values
    # and the points-allowed ladder are separate because they are
    # different kinds of number: one is per occurrence, the other is per
    # game landed in a band.
    dst: dict[str, float] = field(default_factory=dict)
    dst_pa: dict[str, float] = field(default_factory=dict)
    dst_ya: dict[str, float] = field(default_factory=dict)
    # Turnover-return yardage only -- interception and fumble returns,
    # the same two fields the IDP side divides. Kick and punt return
    # yards are stored too but belong to the returner in most leagues,
    # so they are deliberately not rolled in here.
    dst_ret_yds_per_pt: float = 0.0
    # How far up the board the mock room moves this league's QBs. None
    # derives it from the scoring above; the two verified leagues carry
    # values tuned against real draft behaviour instead.
    qb_boost_override: float | None = None
    # Bonuses this league pays for a single game's line -- 4 points at 400
    # passing yards, and so on. They are real scoring and they are NOT in
    # `score_offense`, because a season aggregate cannot tell one 175-yard
    # game from two 90-yard games. Kept as descriptions rather than values
    # so a surface can name what it is missing instead of implying a
    # number it does not have; a league carrying any reads as a floor.
    per_game_bonuses: tuple[str, ...] = ()

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
    def starts_dst(self) -> bool:
        """Whether this league drafts whole team defenses. Independent of
        `starts_idp`: plenty of leagues do one, some do both."""
        return "DEF" in self.slots

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
    def qb_spread_premium_per_game(self) -> float:
        """The part of the premium that actually separates QB1 from QB12.

        The distinction this property exists to make, found Aug 21 by
        checking the derived boost against the two overrides that were
        tuned on real draft behaviour. They disagreed by roughly 2x, and
        the reason is structural rather than a bad constant.

        **A premium every starting quarterback earns changes nobody's
        draft order.** RED_EYE pays a point per completion. QB1 completes
        about 22 a game and so does the twelfth-best starter, so the
        bonus adds ~22 points per game to *every* QB and moves none of
        them relative to the others -- while `qb_premium_per_game`, which
        measures level against the market, counts all 22 as a reason to
        draft one early.

        Touchdown and yardage bonuses are different: they scale with how
        good the quarterback is, so richer values there really do widen
        the gap between the best and the replacement. Those stay.

        **Still an estimate**, and the remaining error is the same kind,
        smaller: the TD and yardage terms use one starter's volume rather
        than the spread between a starter and a replacement. Closing that
        needs measured per-QB lines, which is a real piece of work -- see
        docs/GAP_REVIEW.md. The two verified leagues carry overrides
        precisely because this is not yet measured.
        """
        td = (self.pass_td - MARKET_PASS_TD) * QB_TD_PER_GAME
        yards = QB_PASS_YDS_PER_GAME * (1 / self.pass_yds_per_pt - 1 / MARKET_PASS_YDS_PER_PT)
        return round(td + yards, 2)

    @property
    def qb_draft_boost(self) -> float:
        """The QB premium expressed as draft slots, for the mock room.

        An explicit override wins, because the two verified leagues were
        tuned against how their rooms actually draft. Otherwise derive
        from the *spread* premium and cap: the derivation is directionally
        right and numerically crude, so it is not allowed to produce a
        boost larger than two rounds however extreme the scoring gets.
        """
        if self.qb_boost_override is not None:
            return self.qb_boost_override
        derived = self.qb_spread_premium_per_game / POINTS_PER_ROUND * self.teams
        return round(min(derived, MAX_DERIVED_QB_BOOST), 1)

    def score_player(self, stats: dict, idp_group: str | None = None) -> float | None:
        """One player's total here, or None when this league cannot start him.

        The dispatch rule, in one place. A player is scored exactly one
        way -- offence, or as an individual defender -- decided by what
        the league can actually start, so nobody is counted twice and no
        unrosterable player gets a number. `None` is the honest answer for
        "no slot", and callers must render it as a dash rather than a zero:
        a defensive lineman in a league with no DL slot would score
        perfectly well and be perfectly undraftable.

        Team defenses go through `score_dst` instead -- they are not
        players and are not comparable to one on volume.
        """
        if idp_group:
            if idp_group not in self.idp_groups:
                return None
            return self.score_idp(stats)
        return self.score_offense(stats)

    @property
    def has_per_game_bonuses(self) -> bool:
        """Whether a season total under-reads this league's real scoring."""
        return bool(self.per_game_bonuses)

    @property
    def receiving_is_halved(self) -> bool:
        return self.rec_yds_per_pt > MARKET_REC_YDS_PER_PT

    def score_offense(self, stats: dict) -> float:
        """One offensive player's total under this league's settings.

        The half that was missing. `score_idp` and `score_dst` have scored
        defenders against league rules since August; offence had every
        scoring VALUE and none of the stats they multiply, so the app
        could not total a single quarterback (owner ask, Aug 21).

        Kickers are included -- every league starts one and six are on the
        board -- at a flat value per made field goal. Yahoo's distance
        tiers are a per-league setting this repo has not verified, and
        guessing 3/4/5 by yardage would be inventing a number.

        **Known undercount, BALLAPALOSA only.** Its per-game bonuses (4 at
        400 passing yards, 4 at 175 rushing or receiving, 4 for a 40-plus
        yard TD) cannot be derived from season aggregates -- a 175-yard
        game and two 90-yard games look identical in a total. Weekly lines
        would settle it; until then that league reads slightly low, and
        this note is the label rather than a silent difference.
        """
        pts = stats.get("rec", 0) * self.ppr
        for stat_key, per_pt in (
            ("rec_yd", self.rec_yds_per_pt),
            ("rush_yd", self.rush_yds_per_pt),
            ("pass_yd", self.pass_yds_per_pt),
        ):
            if per_pt:
                pts += stats.get(stat_key, 0) / per_pt
        pts += stats.get("pass_cmp", 0) * self.pass_completion
        pts += stats.get("pass_td", 0) * self.pass_td
        pts += stats.get("rush_td", 0) * self.rush_td
        pts += stats.get("rec_td", 0) * self.rec_td
        pts += stats.get("pass_int", 0) * self.pass_int
        pts += stats.get("fum_lost", 0) * self.fum_lost
        two = stats.get("pass_2pt", 0) + stats.get("rush_2pt", 0) + stats.get("rec_2pt", 0)
        pts += two * self.two_pt
        pts += stats.get("fgm", 0) * self.fg_made
        pts += stats.get("xpm", 0) * self.xp_made
        # Returns -- the hidden value docs/LEAGUES.md point 5 promises
        # and the scorer silently ignored until Aug 22: a full-time
        # returner's ~1,000 kick-return yards are 50 real points in the
        # two 20 yds/pt leagues. Field names verified live (probe run 12).
        if self.ret_yds_per_pt:
            pts += (stats.get("kr_yd", 0) + stats.get("pr_yd", 0)) / self.ret_yds_per_pt
        pts += (stats.get("kr_td", 0) + stats.get("pr_td", 0)) * self.ret_td
        return round(pts, 1)

    def score_idp(self, stats: dict) -> float:
        """One defender's season total under this league's settings."""
        points = sum(stats.get(f, 0) * v for f, v in self.idp.items())
        returns = stats.get("idp_int_ret_yd", 0) + stats.get("idp_fum_ret_yd", 0)
        if self.idp_ret_yds_per_pt:
            points += returns / self.idp_ret_yds_per_pt
        return round(points, 1)

    def score_dst(self, stats: dict) -> float:
        """One team defense's season total under this league's settings.

        The per-event half is a straight product. The tiered halves
        multiply each band's value by the number of games the team
        finished inside it -- which is exactly what Sleeper stores, so
        no game-by-game reconstruction is involved.
        """
        points = sum(stats.get(f, 0) * v for f, v in self.dst.items())
        points += sum(stats.get(f, 0) * v for f, v in self.dst_pa.items())
        points += sum(stats.get(f, 0) * v for f, v in self.dst_ya.items())
        if self.dst_ret_yds_per_pt:
            returns = stats.get("int_ret_yd", 0) + stats.get("fum_ret_yd", 0)
            points += returns / self.dst_ret_yds_per_pt
        return round(points, 1)

    def to_dict(self) -> dict:
        """Plain data, for the store and for the browser."""
        return {
            "key": self.key,
            "name": self.name,
            "teams": self.teams,
            "yahoo_id": self.yahoo_id,
            "slots": list(self.slots),
            "ppr": self.ppr,
            "pass_td": self.pass_td,
            "pass_yds_per_pt": self.pass_yds_per_pt,
            "pass_completion": self.pass_completion,
            "rec_yds_per_pt": self.rec_yds_per_pt,
            "rush_yds_per_pt": self.rush_yds_per_pt,
            "rush_td": self.rush_td,
            "rec_td": self.rec_td,
            "pass_int": self.pass_int,
            "fum_lost": self.fum_lost,
            "two_pt": self.two_pt,
            "fg_made": self.fg_made,
            "xp_made": self.xp_made,
            "ret_yds_per_pt": self.ret_yds_per_pt,
            "ret_td": self.ret_td,
            "idp": dict(self.idp),
            "idp_ret_yds_per_pt": self.idp_ret_yds_per_pt,
            "dst": dict(self.dst),
            "dst_pa": dict(self.dst_pa),
            "dst_ya": dict(self.dst_ya),
            "dst_ret_yds_per_pt": self.dst_ret_yds_per_pt,
            "qb_boost_override": self.qb_boost_override,
            "per_game_bonuses": list(self.per_game_bonuses),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> League:
        """Rebuild from stored data, ignoring anything unrecognised so an
        older or hand-edited blob cannot crash the scoring path."""
        known = {f for f in cls.__dataclass_fields__ if f != "slots"}
        kwargs = {k: v for k, v in (raw or {}).items() if k in known}
        kwargs["slots"] = tuple(raw.get("slots") or ())
        kwargs["per_game_bonuses"] = tuple(raw.get("per_game_bonuses") or ())
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
    yahoo_id="192426",
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
    ret_yds_per_pt=20.0,
    ret_td=6.0,
    idp=dict(_BASE_IDP),
    idp_ret_yds_per_pt=20.0,
    qb_boost_override=10.0,
)

RED_EYE = League(
    key="red_eye",
    name="RED_EYE",
    teams=12,  # owner correction Aug 20, superseding the PDF's 10
    yahoo_id="811739",
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
    ret_yds_per_pt=20.0,
    ret_td=6.0,
    idp={**_BASE_IDP, "idp_sack": 2.0, "idp_int": 3.0},
    idp_ret_yds_per_pt=10.0,
    qb_boost_override=18.0,
)

BALLAPALOSA = League(
    key="ballapalosa",
    name="BALLAPALOSA",
    teams=10,
    yahoo_id="963878",
    # QB / 3 WR / 2 RB / TE / W-R-T / K / DEF, then six bench. The two IR
    # slots on the settings page are not draft rounds and are left out --
    # counting them would tell the mock room to run two rounds longer
    # than the real draft does.
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
        "DEF",
        *(("BN",) * 6),
    ),
    # Offense: 6-pt passing TDs and a full point per completion, but
    # market yardage on all three -- so this room pays QBs well above
    # market without the halved receiving of the other two.
    pass_td=6.0,
    pass_yds_per_pt=25.0,
    pass_completion=1.0,
    rec_yds_per_pt=10.0,
    # Its settings page pays return TDs but no return yardage.
    ret_td=6.0,
    # No IDP at all. This is the team-defense league.
    idp={},
    idp_ret_yds_per_pt=0.0,
    dst={
        "sack": 1.0,
        "int": 1.0,  # Yahoo default is 2 -- this league pays 1
        "fum_rec": 1.0,  # likewise
        "def_st_td": 6.0,  # "Touchdown" and "Kickoff and Punt Return TD" both 6
        "safe": 2.0,
        "blk_kick_any": 2.0,
        "def_4_and_stop": 5.0,  # Yahoo default 0
    },
    dst_pa={
        "pts_allow_0": 10.0,
        "pts_allow_1_6": 7.0,
        "pts_allow_7_13": 4.0,
        "pts_allow_14_20": 1.0,
        "pts_allow_28_34": -1.0,
        "pts_allow_35p": -2.0,  # Yahoo default -4
    },
    # Yahoo states three bands (300-399, 400-499, 500+); Sleeper buckets
    # more finely, so each Yahoo band maps onto the two beneath it.
    dst_ya={
        "yds_allow_300_349": -1.0,
        "yds_allow_350_399": -1.0,
        "yds_allow_400_449": -2.0,
        "yds_allow_450_499": -2.0,
        "yds_allow_500_549": -3.0,
        "yds_allow_550p": -3.0,
    },
    # Deliberately not overridden. The other two carry boosts tuned
    # against how those rooms actually draft; nobody has watched this one
    # draft, so it derives its own like any user league would -- and the
    # editor says "derived, capped" rather than implying a measurement.
    qb_boost_override=None,
    # From the settings page, Aug 21. The only league of the three that
    # pays them, and the reason its season totals read as a floor.
    per_game_bonuses=(
        "4 pts at 400 passing yards",
        "4 pts at 175 rushing or receiving yards",
        "4 pts for a 40-plus yard touchdown",
    ),
)

DEFAULTS: tuple[League, ...] = (NDDPL, RED_EYE, BALLAPALOSA)


def defaults() -> list[League]:
    return list(DEFAULTS)


def user_leagues(data: dict | None) -> list[League]:
    """One user's own leagues, rebuilt from their stored blob.

    Anything unreadable is dropped rather than raised. Stored settings
    outlive the code that wrote them, and a board that 500s the morning
    of a draft is worse than one missing a league.
    """
    out = []
    for raw in (data or {}).get("leagues") or []:
        try:
            out.append(League.from_dict(raw))
        except Exception:  # noqa: BLE001 - a bad blob must not blank the page
            _log.warning("league settings: dropped an unreadable stored league")
    return out


def for_user(data: dict | None) -> list[League]:
    """The owner's verified two, then whatever this user defined. What
    every league-aware surface should render for a given sign-in."""
    return defaults() + user_leagues(data)


def slots_from_counts(counts: dict) -> tuple[str, ...]:
    """A lineup card's counts as the slot tuple everything else reads."""
    out: list[str] = []
    for slot in SLOT_ORDER:
        try:
            n = int(counts.get(slot) or 0)
        except (TypeError, ValueError):
            n = 0
        out.extend([slot] * max(0, n))
    return tuple(out)


def counts_from_slots(slots: tuple[str, ...]) -> dict[str, int]:
    return {slot: sum(1 for s in slots if s == slot) for slot in SLOT_ORDER}


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
        # Not inherited. `replace` copies every field not named here, so
        # without this a league somebody defines by hand carries the
        # OWNER'S Yahoo id and links to the owner's league from a
        # stranger's settings page. Same rule the invite email learned:
        # the owner's teams do not travel with anything.
        yahoo_id="",
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
        ret_yds_per_pt=0.0,
        ret_td=0.0,
        idp={},
        idp_ret_yds_per_pt=0.0,
        # Not inherited: NDDPL's boost was tuned against how that room
        # actually drafts, and applying it to somebody else's league
        # would be an invented number wearing a verified one's clothes.
        # None means "derive it from the scoring they entered".
        qb_boost_override=None,
    )
