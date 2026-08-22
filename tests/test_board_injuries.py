"""The draft board's injury badge, pointed at live data.

Owner, Aug 22: *"what happens when a player is put on IR"* — and on the
board they actually draft from, the honest answer was **nothing**.

The badge came from two hand-typed name lists in the design document:
six names in `OUT_RED`, thirteen in `INJ_YELLOW`, frozen at whatever the
injury report said the day they were written. Nothing in `app/` ever
touched them. So a player placed on IR today got no badge at all, and the
nineteen wore theirs permanently whatever their real status — George
Kittle reading "PUP / IR" while healthy.

The app has had Sleeper's `injury_status` on every sync for weeks. It
already drives /app/nextup, /app/idp, /app/scoring and the mock room's
display. This board was the one surface still reading the frozen list.
"""

from __future__ import annotations

import json
import re

from app.feeds import board
from app.feeds import players as players_mod

INDEX_HTML = open("frontend/index.html", encoding="utf-8").read()


def _index(**flags: str | None) -> dict:
    return {
        "players": {
            str(i): {
                "id": str(i),
                "name": name,
                "position": "WR",
                "team": "SF",
                "injury_status": flag,
                "rank": 10 + i,
            }
            for i, (name, flag) in enumerate(flags.items())
        }
    }


# --- the vocabulary, owned once -----------------------------------------


def test_the_out_flags_are_the_kernels_not_a_second_copy():
    """`depth` decides whether an absence is a pickup trigger and `board`
    decides which badge a row wears. Two copies is how one goes stale —
    which is the bug this whole change is about."""
    from app.feeds import depth

    assert depth.OUT_FLAGS is players_mod.OUT_FLAGS


def test_ir_counts_as_out():
    assert players_mod.injury_tier("IR") == "out"
    for flag in ("Out", "PUP", "Sus", "NA", "Doubtful", "DNR"):
        assert players_mod.injury_tier(flag) == "out", flag


def test_questionable_is_a_flag_but_not_an_absence():
    """A questionable starter is not a pickup trigger — treating him as
    one would cry wolf every week — but the board should still say so."""
    assert players_mod.injury_tier("Questionable") == "questionable"


def test_no_flag_is_no_badge():
    for blank in (None, "", "   "):
        assert players_mod.injury_tier(blank) == ""


def test_an_unrecognised_flag_is_shown_rather_than_dropped():
    """Sleeper can add a status. A flag we cannot classify is still a
    flag, and silently hiding it is the more confident mistake."""
    assert players_mod.injury_tier("Limited Participation") == "questionable"


# --- the map -------------------------------------------------------------


def test_only_flagged_players_are_carried():
    table = board.injuries(_index(**{"Brock Bowers": "IR", "Bijan Robinson": None}))
    assert set(table) == {"Brock Bowers"}


def test_the_badge_carries_the_real_word_not_a_category():
    """ "IR" is more use than "PUP / IR", and it is one fewer translation
    between the source and the reader."""
    table = board.injuries(_index(**{"Brock Bowers": "IR", "Puka Nacua": "Questionable"}))
    assert table["Brock Bowers"] == {"flag": "IR", "out": True}
    assert table["Puka Nacua"] == {"flag": "Questionable", "out": False}


# --- it reaches the page -------------------------------------------------


def test_the_frozen_name_lists_are_gone():
    out, n = board.inject_injuries(INDEX_HTML, _index(**{"Brock Bowers": "IR"}))
    assert n == 1
    assert "const OUT_RED" not in out
    assert "const INJ_YELLOW" not in out
    assert '"PUP / IR"' not in out, "the hardcoded label went with them"


def test_the_badge_reads_the_live_map():
    out, _ = board.inject_injuries(INDEX_HTML, _index(**{"Brock Bowers": "IR"}))
    assert "FB_INJURIES[name]" in out
    table = json.loads(re.search(r"const FB_INJURIES = (\{.*?\});\n", out, re.S).group(1))
    assert table["Brock Bowers"]["flag"] == "IR"


def test_a_player_who_recovered_loses_his_badge():
    """The half that the frozen list could never do. George Kittle was in
    OUT_RED; healthy, he must now carry nothing."""
    out, _ = board.inject_injuries(INDEX_HTML, _index(**{"George Kittle": None}))
    table = json.loads(re.search(r"const FB_INJURIES = (\{.*?\});\n", out, re.S).group(1))
    assert "George Kittle" not in table


def test_a_newly_injured_player_gains_one():
    """The other half. Nobody could be added to a hand-typed list without
    a deploy."""
    out, _ = board.inject_injuries(INDEX_HTML, _index(**{"Jahmyr Gibbs": "IR"}))
    table = json.loads(re.search(r"const FB_INJURIES = (\{.*?\});\n", out, re.S).group(1))
    assert table["Jahmyr Gibbs"] == {"flag": "IR", "out": True}


def test_an_empty_index_clears_every_badge_rather_than_keeping_stale_ones():
    """No index is a real state — it happened for hours on Aug 22. No
    badges is the truthful rendering of "we do not know", and it is
    better than nineteen names asserting a status from weeks ago."""
    out, n = board.inject_injuries(INDEX_HTML, None)
    assert n == 0
    assert "const OUT_RED" not in out, "the frozen list must not survive as a fallback"
    assert "const FB_INJURIES = {};" in out


def test_both_edits_land_or_neither_does():
    """A map beside the surviving lists changes nothing; a rebound lookup
    with no map clears every badge. Either alone is worse than neither."""
    without = INDEX_HTML.replace('const OUT_RED = ["Ricky Pearsall"', 'const OUT_RED = ["Nobody"')
    out, n = board.inject_injuries(without, _index(**{"Brock Bowers": "IR"}))
    assert n == 0
    assert "FB_INJURIES" not in out


# --- out for the season comes off the board -----------------------------
# Owner, Aug 22: "if they are out for season drop off list, if they are
# only out for a few weeks leave."


def _board_rows(html: str) -> list[str]:
    block = re.search(r"const RAW_BOARD = \[(.*?)\n\];", html, re.S)
    return re.findall(r'^\s*\[\d+,"([^"]+)"', block.group(1), re.M)


COMMITTED = _board_rows(INDEX_HTML)


def test_the_split_is_reserve_list_versus_weekly_status():
    """Sleeper publishes no season-ending field — `injury_status` says
    what a player is designated as, never for how long. So the line falls
    where the data draws one: a reserve list carries a multi-week minimum
    and takes a player off a draft board; a weekly game status does not."""
    for flag in ("IR", "PUP", "NA", "DNR", "Sus"):
        assert players_mod.is_reserve(flag), flag
    for flag in ("Out", "Doubtful", "Questionable"):
        assert not players_mod.is_reserve(flag), flag


def test_a_player_on_ir_leaves_the_board():
    name = COMMITTED[18]
    out, dropped = board.drop_reserve(INDEX_HTML, _index(**{name: "IR"}))
    assert dropped == [name]
    assert name not in _board_rows(out)


def test_a_player_out_for_a_week_stays_on_it():
    """The other half of the rule, and the one that is easy to get wrong:
    out this Sunday is still worth drafting in August."""
    name = COMMITTED[4]
    out, dropped = board.drop_reserve(INDEX_HTML, _index(**{name: "Out"}))
    assert dropped == []
    assert name in _board_rows(out)


def test_a_healthy_player_stays():
    name = COMMITTED[0]
    _, dropped = board.drop_reserve(INDEX_HTML, _index(**{name: None}))
    assert dropped == []


def test_deepen_does_not_hand_the_row_straight_back():
    """The bug this hit the first time it was wired. `deepen` backfills
    from the same index, so it re-added the player the board had just
    dropped — the log read "dropped 1" and "appended 1" in consecutive
    lines. Backfill must never seat someone on a reserve list."""
    from app import leagues as leagues_mod

    index = {
        "players": {
            "1": {
                "id": "1",
                "name": "Somebody Benched",
                "position": "WR",
                "team": "SF",
                "injury_status": "IR",
                "rank": 1,
            }
        }
    }
    out, added = board.deepen(INDEX_HTML, index, leagues_mod.defaults())
    assert "Somebody Benched" not in _board_rows(out)


def test_nothing_is_dropped_without_an_index():
    """No index is not "everyone is healthy" and it is not "drop
    everyone" either — it is no information, so the board is untouched."""
    out, dropped = board.drop_reserve(INDEX_HTML, None)
    assert dropped == []
    assert out == INDEX_HTML


def test_coming_off_ir_puts_him_back_with_no_list_to_edit():
    """The whole reason this is safe to automate. The flag is live, so
    recovery is just the next sync — nobody maintains a return list."""
    name = COMMITTED[18]
    hurt, dropped = board.drop_reserve(INDEX_HTML, _index(**{name: "IR"}))
    assert name not in _board_rows(hurt)
    healed, dropped_again = board.drop_reserve(INDEX_HTML, _index(**{name: None}))
    assert dropped_again == []
    assert name in _board_rows(healed)
