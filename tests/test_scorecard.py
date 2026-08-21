"""The prediction ledger and the scorecard page.

Owner asked how to improve the AI predictions and whether two models
would help. The honest answer was that nothing had ever checked whether a
call was right, so there was no way to tell whether any change helped.
This is that check.

The contract has three parts, and each one is a way the number could
become a lie:

  * **Recording is immutable.** A prediction that can be revised after
    the outcome is not a prediction. Re-running the sync must not move a
    stored call by a single point.
  * **Only settled, falsifiable calls count.** Unplayed games and pushes
    are excluded from the rate rather than folded in.
  * **Calibration is reported, not just the rate.** "Said 78, hit 52" is
    the finding; a bare 52% hides it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.feeds import accuracy, scorecard

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def _preds() -> list[dict]:
    return [
        {
            "name": "Josh Allen",
            "meta": "QB · BUF",
            "prop": "Passing TDs",
            "line": "1.5",
            "lean": "OVER",
            "conf": 78,
            "why": "x",
        },
        {
            "name": "Derrick Henry",
            "meta": "RB · BAL",
            "prop": "Rushing TDs",
            "line": "0.5",
            "lean": "OVER",
            "conf": 74,
            "why": "x",
        },
        {
            "name": "Patrick Mahomes",
            "meta": "QB · KC",
            "prop": "Passing TDs",
            "line": "1.5",
            "lean": "UNDER",
            "conf": 58,
            "why": "x",
        },
    ]


def _names() -> dict[str, str]:
    return {"josh allen": "a", "derrick henry": "b", "patrick mahomes": "c"}


# --- recording --------------------------------------------------------------


def test_a_recorded_call_can_never_be_edited():
    """The single property that makes this evidence rather than opinion.
    The sync runs every 15 minutes; if a re-run could move a stored
    confidence, the ledger would drift toward whatever is true now."""
    ledger, added = scorecard.record(None, _preds(), 2026, 1, "t0")
    assert added == 3

    louder = [{**p, "conf": 99, "why": "changed my mind"} for p in _preds()]
    ledger, again = scorecard.record(ledger, louder, 2026, 1, "t1")
    assert again == 0
    assert [e["conf"] for e in ledger["entries"]] == [78, 74, 58]
    assert all(e["recorded_at"] == "t0" for e in ledger["entries"])


def test_the_same_call_in_a_later_week_is_a_new_call():
    ledger, _ = scorecard.record(None, _preds(), 2026, 1, "t0")
    ledger, added = scorecard.record(ledger, _preds(), 2026, 2, "t1")
    assert added == 3
    assert len(ledger["entries"]) == 6


def test_an_ungradeable_row_is_not_recorded_at_all():
    """A prop no box score settles would sit open forever and quietly
    inflate the "awaiting result" count."""
    junk = [
        {
            "name": "X",
            "meta": "QB · BUF",
            "prop": "Vibes",
            "line": "1.5",
            "lean": "OVER",
            "conf": 70,
        },
        {
            "name": "Y",
            "meta": "QB · BUF",
            "prop": "Passing TDs",
            "line": "n/a",
            "lean": "OVER",
            "conf": 70,
        },
        {
            "name": "Z",
            "meta": "QB · BUF",
            "prop": "Passing TDs",
            "line": "1.5",
            "lean": "MAYBE",
            "conf": 70,
        },
    ]
    _, added = scorecard.record(None, junk, 2026, 1, "t0")
    assert added == 0


# --- grading ----------------------------------------------------------------


def test_grading_settles_against_the_real_box_score():
    ledger, _ = scorecard.record(None, _preds(), 2026, 1, "t0")
    box = {"a": {"pass_td": 3}, "b": {"rush_td": 0}, "c": {"pass_td": 1}}
    ledger, settled = scorecard.grade(ledger, box, _names(), 2026, 1)
    assert settled == 3
    assert {e["name"]: e["result"] for e in ledger["entries"]} == {
        "Josh Allen": "hit",  # 3 > 1.5, leaned OVER
        "Derrick Henry": "miss",  # 0 < 0.5, leaned OVER
        "Patrick Mahomes": "hit",  # 1 < 1.5, leaned UNDER
    }


def test_a_player_who_did_not_appear_stays_open():
    """ "Did not play" is not a wrong call about what he would do if he
    did. Scoring it a miss would punish the app for an injury."""
    ledger, _ = scorecard.record(None, _preds(), 2026, 1, "t0")
    ledger, settled = scorecard.grade(ledger, {"a": {"pass_td": 2}}, _names(), 2026, 1)
    assert settled == 1
    assert scorecard.summary(ledger)["open"] == 2


def test_a_push_is_not_a_win():
    ledger, _ = scorecard.record(
        None,
        [
            {
                "name": "Josh Allen",
                "meta": "QB · BUF",
                "prop": "Passing TDs",
                "line": "2",
                "lean": "OVER",
                "conf": 70,
            }
        ],
        2026,
        1,
        "t0",
    )
    ledger, _ = scorecard.grade(ledger, {"a": {"pass_td": 2}}, _names(), 2026, 1)
    stats = scorecard.summary(ledger)
    assert ledger["entries"][0]["result"] == "push"
    assert stats["pushed"] == 1 and stats["settled"] == 0 and stats["rate"] is None


def test_grading_is_idempotent_and_scoped_to_its_week():
    ledger, _ = scorecard.record(None, _preds(), 2026, 1, "t0")
    box = {"a": {"pass_td": 3}, "b": {"rush_td": 0}, "c": {"pass_td": 1}}
    ledger, first = scorecard.grade(ledger, box, _names(), 2026, 1)
    ledger, second = scorecard.grade(ledger, box, _names(), 2026, 1)
    assert (first, second) == (3, 0)
    # Week 2's box score must not settle week 1's calls.
    ledger, _ = scorecard.record(ledger, _preds(), 2026, 2, "t1")
    ledger, third = scorecard.grade(ledger, box, _names(), 2026, 3)
    assert third == 0


# --- the numbers ------------------------------------------------------------


def test_calibration_reports_what_was_claimed_against_what_happened():
    """The finding this page exists for: a band that says 78 and hits 33
    is overconfidence, and a bare hit rate would hide it."""
    preds = [
        {
            "name": f"P{i}",
            "meta": "QB · BUF",
            "prop": "Passing TDs",
            "line": "1.5",
            "lean": "OVER",
            "conf": 78,
        }
        for i in range(3)
    ]
    ledger, _ = scorecard.record(None, preds, 2026, 1, "t0")
    names = {f"p{i}": f"p{i}" for i in range(3)}
    box = {"p0": {"pass_td": 3}, "p1": {"pass_td": 0}, "p2": {"pass_td": 1}}
    ledger, _ = scorecard.grade(ledger, box, names, 2026, 1)

    band = next(b for b in scorecard.summary(ledger)["bands"] if b["n"])
    assert band["label"] == "70–79%"
    assert (band["n"], band["claimed"], band["actual"]) == (3, 78, 33)


def test_an_empty_ledger_reports_no_rate_rather_than_zero():
    """0% would read as "the app is always wrong". None reads as "no
    evidence", which is the truth before Week 1."""
    stats = scorecard.summary(None)
    assert stats["rate"] is None and stats["settled"] == 0


# --- the week gate ----------------------------------------------------------


def test_nothing_is_recorded_during_the_preseason():
    """There is no regular-season week to key a call to, and a scorecard
    over zero played games would be an accuracy figure with no evidence."""
    week, reason = scorecard.current_week({"week_label": "Preseason Week 3"})
    assert week is None and "preseason" in reason.lower()
    assert scorecard.current_week({"week_label": "Week 1"})[0] == 1
    assert scorecard.current_week(None)[0] is None


# --- the page ---------------------------------------------------------------


def test_the_page_shows_no_accuracy_before_there_are_games():
    page = accuracy.build_html(None, {"week_label": "Preseason Week 3"}, NOW)
    assert "Nothing recorded yet" in page
    assert "preseason" in page.lower()
    assert "hit rate" not in page.lower()


def test_the_page_waits_rather_than_grading_early():
    ledger, _ = scorecard.record(None, _preds(), 2026, 1, "t0")
    page = accuracy.build_html(ledger, {"week_label": "Week 1"}, NOW)
    assert "Nothing graded yet" in page
    assert "3</b> calls are" in page
    assert "no accuracy figure here until there are games behind it" in page


def test_the_page_reports_the_record_and_the_calibration():
    ledger, _ = scorecard.record(None, _preds(), 2026, 1, "t0")
    box = {"a": {"pass_td": 3}, "b": {"rush_td": 0}, "c": {"pass_td": 1}}
    ledger, _ = scorecard.grade(ledger, box, _names(), 2026, 1)
    page = accuracy.build_html(ledger, {"week_label": "Week 2"}, NOW)
    assert "67%" in page  # 2 of 3
    assert "Calibration" in page
    assert "By prop" in page
    # And it is explicit that prose is not scored.
    assert "unscored" in page


def test_the_route_serves_with_no_ledger_at_all():
    from fastapi.testclient import TestClient

    from app import main as main_mod

    r = TestClient(main_mod.app).get("/app/scorecard")
    assert r.status_code == 200
    assert "Scorecard" in r.text
