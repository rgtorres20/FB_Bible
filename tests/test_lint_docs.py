"""The docs linter, proved against fixture trees.

Every rule gets a bad-input test. A lint rule nobody proved can fail is the
exact bug class this repo keeps hitting -- the green-and-broken check -- and a
docs linter that silently passes everything is worse than none, because it
buys confidence it has not earned.

Each rule takes a root path, so the fixtures here are three-file trees in
tmp_path rather than the real repo. The real repo is linted by running the
script; these tests pin the behaviour.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location("lint_docs", _ROOT / "scripts" / "lint_docs.py")
lint_docs = importlib.util.module_from_spec(_SPEC)
# @dataclass reads the defining module out of sys.modules; a module loaded
# by path is not there unless it is put there first.
sys.modules["lint_docs"] = lint_docs
_SPEC.loader.exec_module(lint_docs)


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


GOOD_CLAUDE = """# rules

10 tests green — 6 Python (`pytest`) and 4 JS (`node --test`) — lint clean.

`/app/mock` is the mock room. **NDDPL** `nfl.l.192426` (10-team).
See [docs/LEAGUES.md](docs/LEAGUES.md).
"""

GOOD_LEAGUES_MD = """# leagues

## NDDPL — `nfl.l.192426`

| | |
|---|---|
| Teams | **10** |

## What this means for the product

Nothing with a Teams row, so not a league section.
"""

GOOD_LEAGUES_PY = '''"""fixture"""

from dataclasses import dataclass


@dataclass(frozen=True)
class League:
    key: str
    name: str
    teams: int


NDDPL = League(key="nddpl", name="NDDPL", teams=10)
DEFAULTS: tuple[League, ...] = (NDDPL,)
'''

GOOD_SKIN = '''"""fixture"""

SERVED_PAGES: tuple[str, ...] = ("/app/mock",)
'''

# The two consumers, each reading the canonical list rather than keeping
# a copy — which is what `rule_one_served_page_list` exists to require.
GOOD_NAV = '''"""fixture"""

from app.feeds import skin

SERVED_PAGES = skin.SERVED_PAGES
'''

GOOD_VERIFY = '''"""fixture"""

from app.feeds import skin

for path in skin.SERVED_PAGES:
    pass
'''


@pytest.fixture
def clean(tmp_path):
    """A tiny tree every rule passes on, for the bad cases to break one at a time."""
    write(tmp_path, "CLAUDE.md", GOOD_CLAUDE)
    write(tmp_path, "docs/LEAGUES.md", GOOD_LEAGUES_MD)
    write(tmp_path, "app/leagues.py", GOOD_LEAGUES_PY)
    write(tmp_path, "app/feeds/skin.py", GOOD_SKIN)
    write(tmp_path, "tests/test_navigation.py", GOOD_NAV)
    write(tmp_path, "scripts/verify_live.py", GOOD_VERIFY)
    return tmp_path


def test_the_clean_tree_passes_every_rule(clean):
    for _label, rule in lint_docs.RULES:
        assert rule(clean) == [], _label


# --- rule 1: test count ---------------------------------------------------


def test_test_count_catches_arithmetic_that_does_not_add_up(clean):
    write(clean, "CLAUDE.md", GOOD_CLAUDE.replace("10 tests green", "603 tests green"))
    problems = lint_docs.rule_test_count(clean)
    assert len(problems) == 1
    assert problems[0].line == 3
    assert "not the claimed 603" in problems[0].message


def test_test_count_catches_the_claim_being_deleted(clean):
    write(clean, "CLAUDE.md", "# rules\n\nno numbers here at all\n")
    problems = lint_docs.rule_test_count(clean)
    assert len(problems) == 1
    assert "tests green" in problems[0].message


def test_test_count_checks_the_real_collected_count(clean):
    """Arithmetic held all three times the count was actually wrong."""
    write(clean, "tests/test_two.py", "def test_a():\n    pass\n\n\ndef test_b():\n    pass\n")
    problems = lint_docs.rule_test_count(clean, collect=True)
    assert len(problems) == 1
    assert "pytest collects 2" in problems[0].message


def test_the_collected_count_is_not_asked_for_by_default(clean):
    """Rules stay cheap and offline unless the runner opts in."""
    write(clean, "tests/test_two.py", "def test_a():\n    pass\n")
    assert lint_docs.rule_test_count(clean) == []


# --- rule 2: links --------------------------------------------------------


def test_links_catches_a_renamed_target(clean):
    (clean / "docs" / "LEAGUES.md").rename(clean / "docs" / "LEAGUE_FACTS.md")
    problems = lint_docs.rule_links(clean)
    assert len(problems) == 1
    assert problems[0].path == "CLAUDE.md"
    assert problems[0].line == 6
    assert "docs/LEAGUES.md" in problems[0].message


def test_links_checks_docs_pages_too_and_resolves_relative_to_the_page(clean):
    write(clean, "docs/README.md", "see [gone](GONE.md) and [up](../CLAUDE.md)\n")
    problems = lint_docs.rule_links(clean)
    assert [p.message for p in problems] == ["link target does not exist: GONE.md"]


def test_links_ignores_urls_anchors_and_code(clean):
    write(
        clean,
        "docs/README.md",
        "[web](https://example.com) [top](#map) [mail](mailto:a@b.c) `[x](NOPE.md)`\n",
    )
    assert lint_docs.rule_links(clean) == []


# --- rule 3: wikilinks ----------------------------------------------------


def test_wikilinks_are_rejected(clean):
    write(clean, "docs/OBSIDIAN.md", "# vault\n\nsee [[LEAGUES]] for the numbers\n")
    problems = lint_docs.rule_no_wikilinks(clean)
    assert len(problems) == 1
    assert (problems[0].path, problems[0].line) == ("docs/OBSIDIAN.md", 3)


def test_a_wikilink_quoted_as_an_example_is_not_a_violation(clean):
    """docs/README.md documents the rule by quoting the thing it forbids."""
    write(clean, "docs/README.md", "write `[LEAGUES.md](LEAGUES.md)`, not `[[LEAGUES]]`\n")
    assert lint_docs.rule_no_wikilinks(clean) == []


def test_a_wikilink_inside_a_fenced_block_is_not_a_violation(clean):
    write(clean, "docs/README.md", "example:\n\n```\n[[LEAGUES]]\n```\n")
    assert lint_docs.rule_no_wikilinks(clean) == []


# --- rule 4: served pages -------------------------------------------------


def test_served_pages_catches_a_page_the_docs_never_mention(clean):
    write(
        clean,
        "app/feeds/skin.py",
        'SERVED_PAGES: tuple[str, ...] = ("/app/mock", "/app/newboard")\n',
    )
    problems = lint_docs.rule_served_pages(clean)
    assert len(problems) == 1
    assert "/app/newboard is in SERVED_PAGES but CLAUDE.md never names it" in problems[0].message


def test_served_pages_catches_a_page_missing_from_the_navigation_list(clean):
    write(clean, "CLAUDE.md", GOOD_CLAUDE + "\nand `/app/newboard` is the other one\n")
    problems = lint_docs.rule_served_pages(clean)
    assert len(problems) == 1
    assert problems[0].path == "app/feeds/skin.py"
    assert "/app/newboard" in problems[0].message


def test_served_pages_reports_a_missing_or_unreadable_list(clean):
    write(clean, "app/feeds/skin.py", "PAGES = ()\n")
    problems = lint_docs.rule_served_pages(clean)
    assert len(problems) == 1
    assert "no SERVED_PAGES assignment" in problems[0].message


def test_a_second_copy_of_the_served_page_list_is_caught(clean):
    """The rule that would have caught the Aug 21 drift. Both copies were
    code, so a rule comparing prose to code saw nothing: /app/scoring
    reached the unit test's list and not the watchdog's, and the new
    page shipped with its way home unverified live."""
    write(
        clean,
        "scripts/verify_live.py",
        'SERVED_PAGES = ("/app/mock",)\nfor path in SERVED_PAGES:\n    pass\n',
    )
    problems = lint_docs.rule_one_served_page_list(clean)
    assert problems, "a duplicated literal must be reported"
    assert any("its own SERVED_PAGES literal" in p.message for p in problems)
    assert all(p.path == "scripts/verify_live.py" for p in problems)


def test_a_consumer_that_walks_some_other_list_is_caught(clean):
    """Deleting the copy is not enough — the consumer has to walk the
    canonical one. A watchdog iterating its own hand-written paths would
    pass the no-literal check while checking the wrong pages."""
    write(clean, "scripts/verify_live.py", 'for path in ("/app/mock",):\n    pass\n')
    problems = lint_docs.rule_one_served_page_list(clean)
    assert any("does not read skin.SERVED_PAGES" in p.message for p in problems)


def test_both_consumers_reading_the_canonical_list_is_clean(clean):
    assert lint_docs.rule_one_served_page_list(clean) == []


def test_served_pages_ignores_served_assets(clean):
    """/app/teams.css is served, but it is not a page with a way back."""
    write(clean, "CLAUDE.md", GOOD_CLAUDE + "\n`/app/teams.css` and `/app/data/feeds.json`\n")
    assert lint_docs.rule_served_pages(clean) == []


# --- rule 5: league facts -------------------------------------------------


def test_league_facts_catches_a_team_count_that_drifted(clean):
    write(clean, "docs/LEAGUES.md", GOOD_LEAGUES_MD.replace("**10**", "**12**"))
    problems = lint_docs.rule_league_facts(clean)
    assert len(problems) == 1
    assert "documented as 12-team" in problems[0].message
    assert "drafts it at 10" in problems[0].message


def test_league_facts_catches_a_league_the_code_does_not_have(clean):
    extra = GOOD_LEAGUES_MD + "\n## GHOSTLEAGUE — `nfl.l.999999`\n\n| Teams | 8 |\n"
    write(clean, "docs/LEAGUES.md", extra)
    messages = [p.message for p in lint_docs.rule_league_facts(clean)]
    assert any("GHOSTLEAGUE is documented but is not a built-in" in m for m in messages)


def test_league_facts_catches_a_built_in_with_no_page(clean):
    py = GOOD_LEAGUES_PY.replace(
        "DEFAULTS: tuple[League, ...] = (NDDPL,)",
        'RED_EYE = League(key="red_eye", name="RED_EYE", teams=12)\n'
        "DEFAULTS: tuple[League, ...] = (NDDPL, RED_EYE)",
    )
    write(clean, "app/leagues.py", py)
    messages = [p.message for p in lint_docs.rule_league_facts(clean)]
    assert any("RED_EYE is a built-in in app/leagues.py but has no section" in m for m in messages)


def test_league_facts_catches_an_id_claude_md_does_not_state(clean):
    write(clean, "docs/LEAGUES.md", GOOD_LEAGUES_MD.replace("192426", "192427"))
    messages = [p.message for p in lint_docs.rule_league_facts(clean)]
    assert any("192427" in m and "not stated in CLAUDE.md" in m for m in messages)


# --- rule 6: design pages -------------------------------------------------


DESIGN_DOC = "# Weights — architecture\n\n**Status: design. Nothing here is built yet.**\n"


def test_design_pages_catches_a_design_linked_as_if_built(clean):
    write(clean, "docs/WEIGHTS.md", DESIGN_DOC)
    write(
        clean,
        "CLAUDE.md",
        GOOD_CLAUDE + "\nThe weighting system ships today: [docs/WEIGHTS.md](docs/WEIGHTS.md).\n",
    )
    problems = lint_docs.rule_design_pages(clean)
    assert len(problems) == 1
    assert "declares itself unbuilt" in problems[0].message
    assert problems[0].line == 8


def test_a_design_link_that_says_it_is_a_design_passes(clean):
    write(clean, "docs/WEIGHTS.md", DESIGN_DOC)
    write(
        clean,
        "CLAUDE.md",
        GOOD_CLAUDE + "\n[docs/WEIGHTS.md](docs/WEIGHTS.md) is planning only — do not build.\n",
    )
    assert lint_docs.rule_design_pages(clean) == []


def test_a_built_page_linked_plainly_is_not_flagged(clean):
    """The rule only ever looks at docs that call themselves unbuilt."""
    write(clean, "docs/LEAGUES.md", GOOD_LEAGUES_MD)
    assert lint_docs.rule_design_pages(clean) == []


# --- the runner -----------------------------------------------------------


def test_main_exits_zero_on_a_clean_tree(clean, capsys):
    assert lint_docs.main(["--no-collect", str(clean)]) == 0
    assert "0 failed" in capsys.readouterr().out


def test_main_exits_one_and_names_the_failed_rule(clean, capsys):
    write(clean, "CLAUDE.md", GOOD_CLAUDE.replace("10 tests green", "99 tests green"))
    assert lint_docs.main(["--no-collect", str(clean)]) == 1
    out = capsys.readouterr().out
    assert "FAIL  test count adds up" in out
    assert "FAILED rules:" in out
