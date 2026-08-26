"""Joining live ADP onto the Draft analyzer board.

The bug this fixes: `const BOARD` derived its "ADP" column from the row's
own index, so rank 25 always read "3.01" and every number built on it --
the delta, the blend slider, the sort -- was arithmetic on a restatement of
the rank. The contract here is that real ADP replaces it, per league size,
and that a player the live board does not cover shows a dash rather than a
second scale's worth of invented number.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.feeds import board

PAGE = Path("frontend/index.html").read_text(encoding="utf-8")


def _state(players: list[dict]) -> dict:
    return {"date": "2026-08-15", "players": players}


def _player(name: str, adp: float, s12: float | None = None, s10: float | None = None) -> dict:
    sizes = {}
    if s12 is not None:
        sizes["12"] = s12
    if s10 is not None:
        sizes["10"] = s10
    return {"name": name, "adp": adp, "position": "RB", "team": "DET", "sizes": sizes}


# --- name matching ---------------------------------------------------------


def test_match_key_folds_suffixes_and_punctuation():
    assert board.match_key("Marvin Harrison Jr.") == board.match_key("Marvin Harrison")
    assert board.match_key("Ja'Marr Chase") == board.match_key("Ja'Marr Chase")
    assert board.match_key("Amon-Ra St. Brown") == "amon ra st brown"
    # A two-token name that happens to end in a suffix token keeps both --
    # dropping it would collapse distinct players.
    assert board.match_key("Jared Verse") == "jared verse"


def test_board_names_reads_the_real_page():
    names = board.board_names(PAGE)
    assert len(names) > 190
    assert "Jahmyr Gibbs" in names
    assert names[0] == "Jahmyr Gibbs"  # board order preserved


# --- the join --------------------------------------------------------------


def test_live_adp_keys_by_the_pages_spelling_and_carries_both_sizes():
    matched = board.live_adp(["Jahmyr Gibbs"], [_player("Jahmyr Gibbs", 2.4, s12=2.1, s10=2.7)])
    assert matched["Jahmyr Gibbs"] == {"a": 2.4, "a12": 2.1, "a10": 2.7}


def test_a_player_drafted_in_only_one_size_keeps_that_number_for_both():
    """Dropping him from a league's column would read as 'undrafted', which
    is a different claim than 'only the deeper format has taken him'."""
    matched = board.live_adp(["Deep Guy"], [_player("Deep Guy", 180.0, s12=180.0)])
    assert matched["Deep Guy"] == {"a": 180.0, "a12": 180.0, "a10": 180.0}


def test_board_players_the_market_has_not_drafted_are_absent():
    matched = board.live_adp(["Jahmyr Gibbs", "Nobody"], [_player("Jahmyr Gibbs", 2.4)])
    assert "Nobody" not in matched


def test_non_numeric_adp_is_skipped_rather_than_coerced():
    matched = board.live_adp(["X"], [{"name": "X", "adp": None, "sizes": {}}])
    assert matched == {}


# --- injection -------------------------------------------------------------


def test_injection_replaces_the_derived_column_with_real_numbers():
    state = _state([_player("Jahmyr Gibbs", 2.4, s12=2.1, s10=2.7)])

    served, covered = board.inject(PAGE, state)

    assert covered == 1
    assert "const FB_LIVE_ADP = " in served
    assert '"Jahmyr Gibbs":{"a":2.4,"a12":2.1,"a10":2.7}' in served
    # The derived arithmetic is gone from the board construction.
    assert 'adp: round + "." + String(pick).padStart(2, "0")' not in served


def test_every_consumer_switches_to_the_league_aware_reader():
    state = _state([_player("Jahmyr Gibbs", 2.4)])

    served, _ = board.inject(PAGE, state)

    assert "const FBAdp = b =>" in served
    assert "const adp = FBAdp(b);" in served
    assert "const earlier = v < FBAdp(b);" in served
    assert "(FBAdp(b) || b.base)" in served
    # No consumer is left reading the old derived string.
    assert "parseFloat(b.adp)" not in served


def test_uncovered_players_show_a_dash_not_a_second_scale():
    state = _state([_player("Jahmyr Gibbs", 2.4)])

    served, _ = board.inject(PAGE, state)

    block = re.search(r"const BOARD = RAW_BOARD\.map.*?\n\}\);", served, re.S).group(0)
    assert 'adp: L ? L.a.toFixed(1) : "\\u2014"' in block
    # ...and its own value stays on the overall-pick scale so `mine` still
    # means something for that row.
    assert "const adpNum = L ? L.a : i + 1;" in block


def test_no_live_adp_serves_the_page_untouched():
    assert board.inject(PAGE, None) == (PAGE, 0)
    assert board.inject(PAGE, {"players": []}) == (PAGE, 0)
    # A live board that covers nobody on our board is the same case.
    assert board.inject(PAGE, _state([_player("Nobody At All", 5.0)])) == (PAGE, 0)


def test_a_changed_const_shape_serves_the_page_untouched():
    """A design-project resync that rewrites the board construction must
    miss cleanly rather than half-patch it."""
    resynced = PAGE.replace("const BOARD = RAW_BOARD.map((r, i) => {", "const BOARD = build(", 1)
    out, covered = board.inject(resynced, _state([_player("Jahmyr Gibbs", 2.4)]))
    assert out == resynced
    assert covered == 0


def test_injected_lookup_is_valid_json_for_every_matched_name():
    """The map is interpolated into JS source; apostrophes and accents in
    real player names must survive as valid literals."""
    names = board.board_names(PAGE)
    state = _state([_player(n, float(i + 1)) for i, n in enumerate(names)])

    served, covered = board.inject(PAGE, state)

    # Keyed by name, so the board's duplicate Jayden Reed row (tier 7 WR32
    # and tier 11 WR38 -- the owner's to reconcile) collapses to one entry
    # and both rows read the same live number, which is correct.
    assert covered == len(set(names))
    literal = re.search(r"const FB_LIVE_ADP = (\{.*?\});\n", served, re.S).group(1)
    parsed = json.loads(literal)
    assert parsed["Ja'Marr Chase"]["a"] > 0
    assert len(parsed) == len(set(names))


def test_the_injected_page_is_still_valid_javascript():
    """The injection rewrites a const the whole board is built from, and a
    syntax error there blanks the app rather than degrading it. Parse every
    inline script block with node; skip if node is unavailable."""
    import shutil
    import subprocess
    import tempfile

    import pytest

    if not shutil.which("node"):
        pytest.skip("node is not available")

    names = board.board_names(PAGE)
    state = _state([_player(n, float(i + 1), s12=float(i + 1)) for i, n in enumerate(names)])
    served, covered = board.inject(PAGE, state)
    assert covered

    blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", served, re.S)
    assert blocks, "no inline scripts found -- the extraction regex went stale"
    for source in blocks:
        if not source.strip():
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
            fh.write(source)
            path = fh.name
        try:
            result = subprocess.run(["node", "--check", path], capture_output=True, text=True)
        finally:
            Path(path).unlink()
        assert result.returncode == 0, result.stderr


# --- embedding in a <script> block -----------------------------------------


def test_a_list_name_a_user_typed_cannot_close_the_data_script():
    """Rank-list names are typed by hand at /app/mine and injected into the
    Draft analyzer as JS source. `json.dumps` escapes quotes but not "/",
    so a name containing "</script>" ends the script element early: the
    board's own code never runs and the rest of the payload renders as
    markup on the page. The escape has to happen on the way in -- the
    browser's parser is not going to give the string back."""
    payload = [
        {
            "key": "mine",
            "name": "My sheet </script><h1>gotcha",
            "n": 3,
            "asOf": "2026-08-22",
            "age": 0,
            "scope": "overall",
            "active": True,
        }
    ]
    served, count = board.inject_sources(PAGE, payload)
    assert count == 1

    literal = re.search(r"const FB_RANK_SOURCES = (\[.*?\]);\n", served, re.S).group(1)
    assert "</script>" not in literal
    assert "<\\/script>" in literal
    # Escaped for the HTML parser only: the name the owner typed is the
    # name the panel shows, so this must not silently mangle their text.
    assert json.loads(literal.replace("<\\/", "</"))[0]["name"] == payload[0]["name"]


def test_every_map_this_module_injects_goes_through_the_one_escaper():
    """Four maps land in the same script element -- live ADP, the rank
    sources, league points and the injury flags -- and the way one of them
    stays unescaped is by having a second escaper. Same rule the wire
    cleaners are held to: two of a thing is how one of them stays broken.
    So `json.dumps` is called in exactly one place here, and it is the
    place that escapes."""
    import inspect

    from app.feeds import page as page_mod

    # Stronger than it used to be. Until Aug 26 this asserted `json.dumps(`
    # appeared exactly once here -- the one call that escapes. Then `page`
    # needed the identical escape for the prefs shim, and the choice was
    # to import a private name, copy the rule, or move it. It moved, to
    # `skin.script_json`, so now the assertion is that NEITHER injector
    # reaches for `json.dumps` at all: there is one escaper and it is not
    # in either of them.
    for module in (board, page_mod):
        source = inspect.getsource(module)
        assert "json.dumps(" not in source, module.__name__
        assert "script_json" in source, module.__name__
    assert "json.dumps(" in inspect.getsource(board._script_json)

    # And it really escapes, at whatever depth the payload nests it.
    assert board._script_json({"Player </script>": ["</b>"]}) == (
        '{"Player <\\/script>":["<\\/b>"]}'
    )


# --- duplicate rows --------------------------------------------------------


def test_dedupe_keeps_the_first_higher_ranking_row():
    """The board carried Jayden Reed at tier 7 (WR32) and again at tier 11
    (WR38). The owner's call was to keep tier 7, which is the first row."""
    served, dropped = board.dedupe(PAGE)

    assert dropped == ["Jayden Reed"]
    names = board.board_names(served)
    assert len(names) == len(set(names))
    block = re.search(r"const RAW_BOARD = \[(.*?)\n\];", served, re.S).group(1)
    reed = [line for line in block.split("\n") if "Jayden Reed" in line]
    assert len(reed) == 1
    assert '[7,"Jayden Reed","WR · GB","WR32"' in reed[0]


def test_dedupe_is_a_no_op_on_a_clean_board():
    once, _ = board.dedupe(PAGE)
    twice, dropped = board.dedupe(once)
    assert dropped == []
    assert twice == once


def test_dedupe_leaves_a_page_without_a_board_alone():
    assert board.dedupe("<html>no board here</html>") == ("<html>no board here</html>", [])


def test_dedupe_renumbers_nothing_but_shortens_the_board():
    """Ranks come from the row's index at render time, so dropping a row
    closes the gap rather than leaving a hole."""
    served, _ = board.dedupe(PAGE)
    assert len(board.board_names(served)) == len(board.board_names(PAGE)) - 1


def test_each_league_reads_its_own_market_size_derived_not_asserted():
    """RED_EYE is 12-team and NDDPL is 10-team (owner correction Aug 20,
    docs/LEAGUES.md), so after the serve-time rename the reader must hand
    RED_EYE the a12 column and everyone else a10. It had them BACKWARDS
    until Aug 22 -- codified from this module's own pre-correction note
    that both leagues were 10-team -- so every ADP figure on the analyzer
    read from the wrong market. Derived from `adp_size_key` here so a
    future size correction breaks this test instead of the analyzer.
    """
    from app import leagues as leagues_mod
    from app.feeds import page

    nddpl, red_eye, _ = leagues_mod.defaults()
    assert (nddpl.adp_size_key, red_eye.adp_size_key) == ("a10", "a12")

    served, _ = board.inject(PAGE, _state([_player("Jahmyr Gibbs", 2.4, s12=2.1, s10=2.7)]))
    served, misses = page.league_names(served)
    assert not misses
    helper = re.search(r"const FBAdp = b => \{[^\n]*", served).group(0)
    # The renamed page compares against the real league names, and the
    # 12-team league is the one that gets the 12-team column.
    # adp_size_key is "a10"/"a12" (the payload keys); the board row
    # carries them as adp10/adp12.
    col = lambda lg: "adp" + lg.adp_size_key[1:]  # noqa: E731
    assert f's.draftLeague === "{red_eye.name}" ? b.{col(red_eye)}' in helper
    assert f"b.{col(nddpl)}" in helper
