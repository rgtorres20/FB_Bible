"""Measured depth charts: the arithmetic behind the pickup board.

`app/feeds/depth.py` is what replaced the hand-curated handcuff table, so
its numbers are shown to the owner as fact. The failures worth catching
here are the quiet ones -- an ordering that is not the one the docstring
claims, a divide-by-zero that renders as a measured 0%, a zero standing in
for "this rookie has no last season". Every test below is about a wrong
answer, not a crash.

Fixtures mirror the two real shapes the module joins: the player index
built in `app/feeds/players.py` (`Player.to_dict()`), and the reduced
Sleeper season line stored by `app/feeds/stats.py` (`PLAYER_FIELDS`, in
the floats the live dump carries).
"""

from __future__ import annotations

from app.feeds import depth
from app.feeds import players as players_mod
from app.feeds import stats as stats_mod


def _p(
    pid: str,
    name: str,
    position: str,
    team: str | None = "PHI",
    injury: str | None = None,
    rank: int | None = None,
    **extra: object,
) -> dict:
    """One index row, exactly as `players.Player.to_dict()` emits it."""
    row = {
        "id": pid,
        "name": name,
        "position": position,
        "team": team,
        "injury_status": injury,
        "rank": rank,
    }
    row.update(extra)
    return row


def _index(*players: dict) -> dict:
    return {
        "v": players_mod.INDEX_VERSION,
        "by_name": {},
        "surnames": {},
        "players": {p["id"]: p for p in players},
    }


def _entry(**fields: float) -> dict:
    """One reduced season line. Sleeper hands these back as floats."""
    return {k: float(v) for k, v in fields.items()}


def _stats(players: dict) -> dict:
    return {
        "fetched_at": "2026-08-21T12:00:00+00:00",
        "v": stats_mod.STATS_VERSION,
        "season": 2025,
        "teams": {},
        "players": players,
        "defenses": {},
        "coverage": {"players": {"rush_att": len(players)}},
    }


# A real-shaped room: a bell-cow back, his backup, a third man, and the
# passing game behind them.
ROOM = _index(
    _p("4034", "Saquon Barkley", "RB", rank=2),
    _p("8155", "Will Shipley", "RB", rank=214),
    _p("9502", "Third Stringer", "RB", rank=488),
    _p("4881", "Jalen Hurts", "QB", rank=18),
    _p("7002", "Backup Passer", "QB", rank=402),
    _p("8112", "A.J. Brown", "WR", rank=9),
    _p("6803", "DeVonta Smith", "WR", rank=27),
)

LINES = _stats(
    {
        "4034": _entry(
            gp=16, rush_att=345, rec_tgt=43, rush_rz_att=48, off_snp=720, tm_off_snp=1090
        ),
        "8155": _entry(gp=15, rush_att=28, rec_tgt=9, rush_rz_att=3, off_snp=118, tm_off_snp=1090),
        "9502": _entry(gp=9, rush_att=11, rec_tgt=2, off_snp=40, tm_off_snp=1090),
        "4881": _entry(gp=17, pass_att=560, rush_att=150, pass_rz_att=61, rush_rz_att=41),
        "8112": _entry(gp=17, rec_tgt=158, rec=98, rec_rz_tgt=21, off_snp=980, tm_off_snp=1090),
        "6803": _entry(gp=17, rec_tgt=112, rec=76, rec_rz_tgt=12, off_snp=940, tm_off_snp=1090),
    }
)


# --- the out boundary -------------------------------------------------------


def test_the_out_vocabulary_is_exactly_this_and_questionable_is_outside_it():
    """The whole board keys off this set, so widening it silently is how
    the page starts crying wolf. Questionable is out of it by design (a
    questionable starter is not a pickup trigger); Doubtful is inside it,
    which the module comment does not say and a reader would guess wrong."""
    assert depth.OUT_FLAGS == {"Out", "IR", "PUP", "Sus", "NA", "Doubtful", "DNR"}
    assert "Questionable" not in depth.OUT_FLAGS
    assert "Doubtful" in depth.OUT_FLAGS


def test_is_out_matches_the_flag_exactly_and_treats_no_flag_as_playing():
    """Healthy players carry "" (chart strips a None), and the match is
    exact -- an unrecognised or differently-cased flag reads as playing,
    which is the safe direction but only because normalisation happens
    upstream in chart()."""
    assert depth.is_out({"injury": "Out"}) is True
    assert depth.is_out({"injury": ""}) is False
    assert depth.is_out({}) is False
    assert depth.is_out({"injury": "out"}) is False
    assert depth.is_out({"injury": "Questionable"}) is False


def test_chart_normalises_the_flag_before_is_out_ever_sees_it():
    """Sleeper hands back None for a healthy player and pads some values;
    both have to land as a clean string or the exact match misfires."""
    index = _index(
        _p("1", "Padded Flag", "RB", injury="  Out  ", rank=5),
        _p("2", "Clean Flag", "RB", rank=6),
    )
    rows = depth.chart(index, None)[("PHI", "RB")]
    assert rows[0]["injury"] == "Out"
    assert depth.is_out(rows[0]) is True
    assert rows[1]["injury"] == ""


# --- opportunity ------------------------------------------------------------


def test_a_backs_opportunity_is_carries_plus_targets():
    assert depth.opportunity(LINES["players"]["4034"], "RB") == 388.0
    assert depth.opportunity(LINES["players"]["4034"], "FB") == 388.0


def test_a_receivers_opportunity_ignores_carries():
    """A gadget receiver's handful of jet sweeps must not float him up his
    own depth chart -- targets are the whole measure at WR and TE."""
    gadget = _entry(gp=17, rec_tgt=40, rush_att=30)
    assert depth.opportunity(gadget, "WR") == 40.0
    assert depth.opportunity(gadget, "TE") == 40.0


def test_a_quarterbacks_opportunity_is_attempts_only():
    """Deliberate: a rushing QB's 150 carries are invisible here, so the
    ordering at QB is a passing-volume ordering and nothing else."""
    assert depth.opportunity(LINES["players"]["4881"], "QB") == 560.0


def test_an_unknown_position_falls_back_to_targets_rather_than_crashing():
    """Kickers and anything else off the skill list never reach chart(),
    but the helper is public and must not raise on one."""
    assert depth.opportunity(_entry(rec_tgt=3), "K") == 3.0
    assert depth.opportunity(_entry(rec_tgt=3), "") == 3.0


def test_a_player_with_no_line_scores_zero_opportunity_without_raising():
    """Rookies, free-agent signings and anyone the reducer dropped arrive
    as None. Nulls inside a line (Sleeper omits rather than nulls, but the
    store round-trips JSON) must not poison the sum either."""
    assert depth.opportunity(None, "RB") == 0.0
    assert depth.opportunity({}, "RB") == 0.0
    assert depth.opportunity({"gp": 17.0}, "RB") == 0.0
    assert depth.opportunity({"rush_att": None, "rec_tgt": 12.0}, "RB") == 12.0


# --- usage ------------------------------------------------------------------


def test_no_line_returns_an_empty_dict_so_the_page_can_say_no_25_usage():
    """The honesty rule the module was written around: a rookie has no
    last season, and zeros would read as a measurement that he was given
    nothing. Empty is the answer the renderer keys off."""
    assert depth.usage(None) == {}
    assert depth.usage({}) == {}


def test_rush_share_is_absent_rather_than_zero_when_there_were_no_touches():
    """The divide-by-zero guard. A quarterback's line has neither carries
    nor targets; emitting 0% would print "0% of his work on the ground"
    as though it had been measured."""
    line = depth.usage(_entry(gp=17, pass_att=489, pass_rz_att=54, off_snp=1050, tm_off_snp=1090))
    assert line != {}  # he played -- the line is real, the split is not there
    assert "rush_share" not in line
    assert line.get("rush_share") is None


def test_snap_share_needs_both_halves_of_the_fraction():
    """off_snp without tm_off_snp is the common partial-coverage case in
    the dump. A team-snap count of zero must suppress the percentage, not
    divide by it."""
    assert "snap_share" not in depth.usage(_entry(gp=17, rec_tgt=50, off_snp=600))
    assert "snap_share" not in depth.usage(_entry(gp=17, rec_tgt=50, off_snp=600, tm_off_snp=0))
    assert "snap_share" not in depth.usage(_entry(gp=17, rec_tgt=50, tm_off_snp=1090))
    assert depth.usage(LINES["players"]["4034"])["snap_share"] == 66  # 720 / 1090


def test_the_ground_split_is_the_measured_one():
    """The number the handcuff table used to guess at."""
    assert depth.usage(_entry(gp=17, rush_att=90, rec_tgt=10))["rush_share"] == 90
    assert depth.usage(LINES["players"]["4034"])["rush_share"] == 89  # 345 of 388


def test_games_played_stays_none_when_the_line_never_carried_it():
    """A defaulted 0 would render as "0 games" beside real carries, which
    is worse than saying nothing."""
    assert depth.usage(_entry(rush_att=40, rec_tgt=6))["gp"] is None
    assert depth.usage(LINES["players"]["4034"])["gp"] == 16.0


def test_usage_reports_the_red_zone_cuts_it_was_given_and_zero_for_the_rest():
    line = depth.usage(LINES["players"]["4034"])
    assert line["rush_att"] == 345.0
    assert line["rec_tgt"] == 43.0
    assert line["rz_att"] == 48.0
    assert line["rz_tgt"] == 0  # rec_rz_tgt absent from a back's line


# --- chart ------------------------------------------------------------------


def test_the_chart_is_ordered_by_what_a_player_was_actually_given():
    """Measured, not asserted -- no free source publishes a depth chart,
    so '25 opportunity is the substitute."""
    board = depth.chart(ROOM, LINES)
    assert [p["name"] for p in board[("PHI", "RB")]] == [
        "Saquon Barkley",
        "Will Shipley",
        "Third Stringer",
    ]
    assert board[("PHI", "RB")][0]["opportunity"] == 388.0
    assert [p["name"] for p in board[("PHI", "WR")]] == ["A.J. Brown", "DeVonta Smith"]


def test_the_tiebreak_is_sleeper_rank_and_the_unranked_sort_last():
    """When two men were given the same work -- and for everyone who was
    given none at all -- rank is the only ordering available. An unranked
    player must fall behind a ranked one on the same opportunity, not
    ahead of him by accident of index order."""
    index = _index(
        _p("1", "Unranked Holdover", "RB", rank=None),
        _p("2", "Lower Ranked", "RB", rank=300),
        _p("3", "Higher Ranked", "RB", rank=55),
    )
    lines = _stats({k: _entry(gp=16, rush_att=30, rec_tgt=10) for k in ("1", "2", "3")})
    assert [p["name"] for p in depth.chart(index, lines)[("PHI", "RB")]] == [
        "Higher Ranked",
        "Lower Ranked",
        "Unranked Holdover",
    ]


def test_a_man_with_neither_a_rank_nor_a_line_is_not_on_the_chart_at_all():
    """The index carries every active body in the league; a third-string
    tight end nobody has heard of is noise on every surface this feeds."""
    index = _index(
        _p("1", "Known Starter", "RB", rank=40),
        _p("2", "Nobody", "RB", rank=None),
    )
    assert [p["name"] for p in depth.chart(index, None)[("PHI", "RB")]] == ["Known Starter"]


def test_an_unranked_player_survives_if_he_actually_played():
    """Rank is popularity; a measured line is evidence. Dropping the
    second would lose exactly the kind of holdover this board exists to
    surface."""
    index = _index(_p("1", "Unranked Holdover", "RB", rank=None))
    board = depth.chart(index, _stats({"1": _entry(gp=16, rush_att=120, rec_tgt=15)}))
    assert [p["name"] for p in board[("PHI", "RB")]] == ["Unranked Holdover"]


def test_players_without_a_club_or_off_the_skill_positions_are_skipped():
    """An unsigned free agent has no depth chart to be on, and kickers and
    team defenses are not what this board ranks. The DEF row is the shape
    `players.py` v4 stores for a team defense."""
    index = _index(
        _p("1", "Free Agent", "RB", team=None, rank=30),
        _p("2", "Kicker", "K", rank=120),
        _p("3", "No Position", None, rank=90),
        _p("4", "Philadelphia Eagles", "DEF", rank=None, dst=True),
        _p("5", "Rostered Back", "RB", rank=40),
    )
    board = depth.chart(index, None)
    assert list(board) == [("PHI", "RB")]
    assert [p["name"] for p in board[("PHI", "RB")]] == ["Rostered Back"]


def test_a_missing_stats_state_yields_a_rank_ordered_chart_not_an_exception():
    """The store can hand back a payload with no stats at all (first sync,
    or a failed one). The chart must still build, with every workload
    honestly empty rather than zeroed."""
    for state in (None, {}, {"v": 4}, {"players": {}}):
        board = depth.chart(ROOM, state)
        rbs = board[("PHI", "RB")]
        assert [p["name"] for p in rbs] == ["Saquon Barkley", "Will Shipley", "Third Stringer"]
        assert all(p["opportunity"] == 0.0 and p["usage"] == {} for p in rbs)


def test_no_index_is_an_empty_chart_not_a_crash():
    assert depth.chart(None, None) == {}
    assert depth.chart({}, LINES) == {}
    assert depth.chart({"players": None}, LINES) == {}


# --- next man up ------------------------------------------------------------


def test_only_a_starter_who_is_really_out_opens_a_vacancy():
    """The boundary, end to end: Doubtful opens a row, Questionable does
    not, and neither does a clean flag."""

    def board(flag):
        index = _index(
            _p("4034", "Saquon Barkley", "RB", injury=flag, rank=2),
            _p("8155", "Will Shipley", "RB", rank=214),
        )
        return depth.next_man_up(index, LINES)

    assert board(None) == []
    assert board("Questionable") == []
    assert len(board("Doubtful")) == 1
    assert len(board("IR")) == 1
    assert len(board("Out")) == 1


def test_the_replacement_skips_anyone_who_is_also_flagged_out():
    index = _index(
        _p("4034", "Saquon Barkley", "RB", injury="Out", rank=2),
        _p("8155", "Will Shipley", "RB", injury="Out", rank=214),
        _p("9502", "Third Stringer", "RB", rank=488),
    )
    row = depth.next_man_up(index, LINES)[0]
    assert row["replacement"]["name"] == "Third Stringer"
    assert row["starter"]["name"] == "Saquon Barkley"


def test_a_room_where_everyone_behind_the_starter_is_also_out_shows_nothing():
    """Pins current behaviour, and it is the sharp edge of this module: the
    week a whole backfield is hurt -- the biggest vacancy on the board --
    the row is dropped entirely rather than named with no replacement."""
    index = _index(
        _p("4034", "Saquon Barkley", "RB", injury="Out", rank=2),
        _p("8155", "Will Shipley", "RB", injury="IR", rank=214),
    )
    assert depth.next_man_up(index, LINES) == []
    solo = _index(_p("4034", "Saquon Barkley", "RB", injury="Out", rank=2))
    assert depth.next_man_up(solo, LINES) == []


def test_the_vacancy_is_the_starters_own_line_never_a_projection():
    """ "Vacated" is what the injured man was given, not a guess at what
    his backup does with it."""
    index = _index(
        _p("4034", "Saquon Barkley", "RB", injury="Out", rank=2),
        _p("8155", "Will Shipley", "RB", rank=214),
        _p("9502", "Third Stringer", "RB", rank=488),
    )
    row = depth.next_man_up(index, LINES)[0]
    assert row["vacated"] == 388.0 == row["starter"]["opportunity"]
    assert row["team"] == "PHI" and row["position"] == "RB"
    assert row["depth"] == ["Saquon Barkley", "Will Shipley", "Third Stringer"]


def test_the_depth_line_is_capped_at_four_names():
    index = _index(
        _p("4034", "Saquon Barkley", "RB", injury="Out", rank=2),
        *(_p(str(i), f"Back {i}", "RB", rank=200 + i) for i in range(1, 6)),
    )
    assert len(depth.next_man_up(index, LINES)[0]["depth"]) == 4


def test_rows_are_ordered_by_raw_opportunity_even_across_positions():
    """Pins current behaviour. The sort compares a quarterback's pass
    attempts against a back's touches on one scale, so an out QB with 560
    attempts always outranks a bell-cow's 388 -- the ordering is volume,
    not fantasy value."""
    index = _index(
        _p("4034", "Saquon Barkley", "RB", injury="Out", rank=2),
        _p("8155", "Will Shipley", "RB", rank=214),
        _p("4881", "Jalen Hurts", "QB", injury="Out", rank=18),
        _p("7002", "Backup Passer", "QB", rank=402),
    )
    rows = depth.next_man_up(index, LINES)
    assert [r["position"] for r in rows] == ["QB", "RB"]
    assert [r["vacated"] for r in rows] == [560.0, 388.0]


def test_a_room_with_no_25_usage_vacates_nothing_and_sorts_last():
    """Two rookies and an injury: the row is real (the flag is live) but
    every number on it is empty, and it must sit below any measured
    vacancy rather than tie with one at zero."""
    index = _index(
        _p("4034", "Saquon Barkley", "RB", injury="Out", rank=2),
        _p("8155", "Will Shipley", "RB", rank=214),
        _p("9601", "Rookie Starter", "WR", injury="Out", rank=64),
        _p("9602", "Rookie Backup", "WR", rank=190),
    )
    rows = depth.next_man_up(index, LINES)
    assert [r["position"] for r in rows] == ["RB", "WR"]
    rookie = rows[-1]
    assert rookie["vacated"] == 0.0
    assert rookie["starter"]["usage"] == {} and rookie["replacement"]["usage"] == {}
    assert rookie["replacement"]["name"] == "Rookie Backup"  # rank order, the only one there is


# --- backups ----------------------------------------------------------------


def test_backups_pairs_each_rooms_second_man_with_its_first():
    row = depth.backups(ROOM, LINES)[0]
    assert (row["team"], row["position"]) == ("PHI", "RB")
    assert row["name"] == "Will Shipley" and row["id"] == "8155"
    assert row["starter"] == "Saquon Barkley"
    assert row["starter_out"] is False
    assert row["rank"] == 214
    assert row["usage"]["rush_att"] == 28.0
    assert row["starter_usage"]["rush_att"] == 345.0


def test_the_starters_share_is_the_measured_slice_of_the_rooms_work():
    """How much of the position's work the starter took -- the higher it
    is, the more the handcuff is worth."""
    assert depth.backups(ROOM, LINES)[0]["starter_share"] == 89  # 388 of the room's 438


def test_the_starters_share_is_none_when_the_room_was_never_measured():
    """The divide-by-zero guard, and the one that matters most: a 0% would
    read as "this starter took none of the work", which is the opposite of
    "nobody here has a last season"."""
    index = _index(
        _p("1", "Rookie Starter", "RB", rank=60),
        _p("2", "Rookie Backup", "RB", rank=190),
    )
    row = depth.backups(index, None)[0]
    assert row["starter_share"] is None
    assert row["usage"] == {} and row["starter_usage"] == {}


def test_a_room_with_one_man_has_no_handcuff_to_offer():
    index = _index(_p("4034", "Saquon Barkley", "RB", rank=2))
    assert depth.backups(index, LINES) == []


def test_backups_flags_a_starter_who_is_out():
    index = _index(
        _p("4034", "Saquon Barkley", "RB", injury="PUP", rank=2),
        _p("8155", "Will Shipley", "RB", rank=214),
    )
    assert depth.backups(index, LINES)[0]["starter_out"] is True


def test_backups_asks_for_one_position_and_honours_the_limit():
    assert [r["name"] for r in depth.backups(ROOM, LINES, position="WR")] == ["DeVonta Smith"]
    assert [r["name"] for r in depth.backups(ROOM, LINES, position="QB")] == ["Backup Passer"]
    assert depth.backups(ROOM, LINES, position="TE") == []

    two_rooms = _index(
        _p("4034", "Saquon Barkley", "RB", rank=2),
        _p("8155", "Will Shipley", "RB", rank=214),
        _p("1", "Other Starter", "RB", team="DAL", rank=30),
        _p("2", "Other Backup", "RB", team="DAL", rank=150),
    )
    assert len(depth.backups(two_rooms, LINES, limit=1)) == 1


def test_the_list_is_ranked_by_the_backups_own_carries_at_every_position():
    """Pins current behaviour. The sort key is the backup's rush_att, so
    at RB it ranks handcuffs by workload as intended -- but at WR every
    key is 0 and the rows come back in index order, which reads as a
    ranking and is not one."""
    rooms = _index(
        # The thin receiving room is listed first, the busy one second.
        _p("1", "Thin Starter", "WR", team="NYG", rank=80),
        _p("2", "Thin Backup", "WR", team="NYG", rank=300),
        _p("8112", "A.J. Brown", "WR", rank=9),
        _p("6803", "DeVonta Smith", "WR", rank=27),
        _p("4034", "Saquon Barkley", "RB", rank=2),
        _p("8155", "Will Shipley", "RB", rank=214),
        _p("3", "Quiet Starter", "RB", team="NYG", rank=44),
        _p("4", "Quiet Backup", "RB", team="NYG", rank=260),
    )
    lines = _stats(
        dict(LINES["players"])
        | {
            "1": _entry(gp=17, rec_tgt=60),
            "2": _entry(gp=17, rec_tgt=8),
            "3": _entry(gp=17, rush_att=120, rec_tgt=20),
            "4": _entry(gp=17, rush_att=9, rec_tgt=4),
        }
    )
    assert [r["name"] for r in depth.backups(rooms, lines, position="RB")] == [
        "Will Shipley",  # 28 carries
        "Quiet Backup",  # 9
    ]
    # 8 targets ahead of DeVonta Smith's 112: index order, not usage.
    assert [r["name"] for r in depth.backups(rooms, lines, position="WR")] == [
        "Thin Backup",
        "DeVonta Smith",
    ]


# --- the wire join ----------------------------------------------------------


NEWER, OLDER = "2026-08-21T10:00:00+00:00", "2026-08-01T10:00:00+00:00"


def _item(item_id: str, title: str, published: str, *tagged: tuple[str, str]) -> dict:
    """A polled wire item after `app/feeds/players.py` has tagged it."""
    return {
        "id": item_id,
        "title": title,
        "link": f"https://example.com/{item_id}",
        "source": "Rotowire",
        "published": published,
        "players": [{"id": pid, "name": name} for pid, name in tagged],
    }


def test_the_join_takes_the_first_item_in_the_list_it_is_handed():
    """ "Newest" is the caller's contract, not this function's arithmetic:
    it never compares `published`, it takes the first match. That is
    correct only because the store keeps items sorted newest-first
    (app/feeds/poller.merge). Handed a list in any other order it returns
    the wrong item, silently -- so the ordering is pinned here."""
    newest_first = [
        _item("a", "Shipley in line for early downs", NEWER, ("8155", "Will Shipley")),
        _item("b", "Older Shipley note", OLDER, ("8155", "Will Shipley")),
    ]
    assert depth.latest_mentions(newest_first, {"8155"})["8155"]["id"] == "a"
    assert depth.latest_mentions(list(reversed(newest_first)), {"8155"})["8155"]["id"] == "b"


def test_the_join_returns_the_real_item_and_only_for_the_ids_asked_for():
    items = [
        _item("a", "Shipley news", NEWER, ("8155", "Will Shipley")),
        _item("b", "Barkley news", OLDER, ("4034", "Saquon Barkley")),
    ]
    found = depth.latest_mentions(items, {"8155"})
    assert set(found) == {"8155"}
    assert found["8155"] is items[0]  # the item itself, never a summary of it


def test_one_item_can_answer_for_every_player_it_tags():
    items = [
        _item("a", "Both backs active", NEWER, ("8155", "Will Shipley"), ("9502", "Third Stringer"))
    ]
    found = depth.latest_mentions(items, {"8155", "9502"})
    assert set(found) == {"8155", "9502"}


def test_an_empty_or_untagged_feed_yields_no_mention_rather_than_a_wrong_one():
    """ "No wire mention yet" is a truthful section; an item tagged with
    nobody, or a payload the store never filled, must not become one."""
    untagged = [
        {"id": "a", "title": "General camp notes", "published": NEWER},
        {"id": "b", "title": "Nobody tagged", "published": NEWER, "players": []},
        {"id": "c", "title": "Malformed tag", "published": OLDER, "players": [{}]},
    ]
    assert depth.latest_mentions(untagged, {"8155"}) == {}
    assert depth.latest_mentions(None, {"8155"}) == {}
    assert depth.latest_mentions([], {"8155"}) == {}
    tagged = [_item("a", "Shipley news", NEWER, ("8155", "Will Shipley"))]
    assert depth.latest_mentions(tagged, set()) == {}
