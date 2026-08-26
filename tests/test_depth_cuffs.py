"""The handcuff table's usage, measured instead of invented.

Owner, Aug 25, after asking where that list comes from: its 32 rows
carried "78% rush · 22% routes" and "24 GL carries" with no source behind
any of them -- numbers shaped like measurements that nobody had measured.
docs/STALE_DATA.md has named this the remaining step since Aug 21,
because depth.usage() already computes the real versions for /app/nextup
and nothing had ever joined them up.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.feeds import depth, players

INDEX = Path("frontend/index.html").read_text(encoding="utf-8")


def _index_for(*names):
    return {"by_name": {players.match_key(n): {"id": str(i)} for i, n in enumerate(names)}}


def _stats(**by_id):
    return {"players": by_id}


def _row(html, name):
    block = re.search(r"const CUFFS = \[(.*?)\n\];", html, re.S).group(1)
    return next(line for line in block.splitlines() if f'name: "{name}"' in line)


PACHECO = {"gp": 16, "rush_att": 180, "rec_tgt": 40, "rush_rz_att": 31}


def test_the_split_is_computed_from_real_carries_and_targets():
    """180 carries against 40 targets is 82% of his touches on the ground.
    The page said 78% and could not say where that came from."""
    served, n = depth.inject_cuffs(INDEX, _index_for("Isiah Pacheco"), _stats(**{"0": PACHECO}))

    assert n > 0
    row = _row(served, "Isiah Pacheco")
    assert "rush: 82" in row
    assert '"82% rush · 18% routes"' in row


def test_the_goal_line_label_moves_with_the_data():
    """The honesty-critical bit. The table said "GL carries · inside the
    5"; Sleeper counts red-zone attempts, inside the 20. Different
    numbers. Putting a red-zone figure under a goal-line label would swap
    an unsourced number for a mislabelled one, which is not an
    improvement -- so the label moves too."""
    served, _ = depth.inject_cuffs(INDEX, _index_for("Isiah Pacheco"), _stats(**{"0": PACHECO}))

    row = _row(served, "Isiah Pacheco")
    assert '"31 RZ carries"' in row
    assert "inside the 20" in row
    assert "inside the 5" not in row
    assert "GL carries" not in row


def test_a_player_the_stats_do_not_cover_keeps_no_number():
    """A rookie has no last season. Zeros that read as a measurement are
    the failure this whole change is about, so the row says so -- the
    same answer /app/nextup already gives."""
    served, _ = depth.inject_cuffs(INDEX, _index_for(), _stats())

    assert served == INDEX, "with nothing measured, nothing is touched"

    served, _ = depth.inject_cuffs(INDEX, _index_for("Isiah Pacheco"), _stats(**{"0": PACHECO}))
    others = [
        line
        for line in re.search(r"const CUFFS = \[(.*?)\n\];", served, re.S).group(1).splitlines()
        if 'name: "' in line and 'name: "Isiah Pacheco"' not in line
    ]
    assert others, "fixture assumes other rows exist"
    assert all("no '25 usage" in line for line in others)
    assert all('gl: "—"' in line for line in others)


def test_the_owners_judgement_is_never_rewritten():
    """starter / risk / cost / why are why this table is worth keeping:
    who is worth a late pick, and the reasoning. Only the four measured
    fields move."""
    before = _row(INDEX, "Isiah Pacheco")
    served, _ = depth.inject_cuffs(INDEX, _index_for("Isiah Pacheco"), _stats(**{"0": PACHECO}))
    after = _row(served, "Isiah Pacheco")

    for field in ("starter", "risk", "cost", "why"):
        original = re.search(rf'{field}: "([^"]*)"', before).group(1)
        assert f'{field}: "{original}"' in after, field


def test_no_escaped_apostrophe_reaches_the_page():
    """A regex replacement template would put a backslash beside the
    apostrophe in "'25" and emit no \\'25 usage into a double-quoted JS
    string. Legal, and visible to anyone reading the source."""
    served, _ = depth.inject_cuffs(INDEX, _index_for("Isiah Pacheco"), _stats(**{"0": PACHECO}))

    block = re.search(r"const CUFFS = \[(.*?)\n\];", served, re.S).group(1)
    assert "\\'" not in block


def test_a_missing_block_changes_nothing():
    broken = INDEX.replace("const CUFFS = [", "const CUFFS_GONE = [", 1)

    served, n = depth.inject_cuffs(broken, _index_for("Isiah Pacheco"), _stats(**{"0": PACHECO}))

    assert n == 0
    assert served == broken


def test_the_join_survives_a_curly_apostrophe():
    """The board's own join key. A name the page spells one way and
    Sleeper spells another must still match, or a real player silently
    reads as "not in the '25 stats"."""
    assert players.match_key("De'Von Achane") == players.match_key("De’Von Achane")
