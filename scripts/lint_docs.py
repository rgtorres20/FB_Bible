"""Docs lint: the claims the documentation makes about the code must hold.

The repo's own rule is "no stale data", and the docs are a surface like any
other -- but nothing checked them. The test count in `CLAUDE.md` was
hand-corrected three times in one day; `docs/STALE_DATA.md` and
`docs/GAP_REVIEW.md` are lint reports maintained by hand. This is the
machine half: the claims a script *can* verify, verified on every push.

The conventions being enforced are stated in `docs/README.md` ("Conventions"),
not invented here.

stdlib only, no network, and it does not run either test suite -- the one
subprocess it shells out to is `pytest --collect-only`, which takes about a
second and answers the one question arithmetic cannot: is 587 still true.

Each rule is a function taking the repo root and returning a list of
`Problem`, so `tests/test_lint_docs.py` can point it at a three-file fixture
tree instead of the real repo. A lint rule nobody proved can fail is the bug
class this repo keeps hitting.

Usage:  python3 scripts/lint_docs.py [--no-collect] [ROOT]
Exits 0 when clean, 1 with a report when not.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Problem:
    """One drifted claim. `path` is relative to the root that was linted."""

    path: str
    line: int
    message: str

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{where} — {self.message}"


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------


def markdown_files(root: Path) -> list[Path]:
    """Every tracked-looking .md in the tree, minus the noise directories.

    Deliberately not `git ls-files`: the rules have to run against a fixture
    tree in tmp_path, which is not a git repo.
    """
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", ".obsidian"}
    out = [p for p in sorted(root.rglob("*.md")) if not (set(p.relative_to(root).parts) & skip)]
    return out


_FENCE = re.compile(r"^\s*(```|~~~)")


def strip_code(text: str) -> list[str]:
    """Lines with fenced blocks and inline code spans blanked out.

    Line numbers are preserved (blanked, never dropped) so a problem can
    still name the line it was found on. Without this, `docs/README.md`'s
    own example of the wikilink you must not write -- ``[[LEAGUES]]`` --
    is reported as a violation of the rule it documents.
    """
    lines = text.splitlines()
    out: list[str] = []
    in_fence = False
    for raw in lines:
        if _FENCE.match(raw):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else re.sub(r"`[^`]*`", "", raw))
    return out


_LINK = re.compile(r"\[(?P<text>[^\]]*)\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)")


def _read(root: Path, rel: str) -> str | None:
    p = root / rel
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


# --------------------------------------------------------------------------
# rule 1 -- the test count in CLAUDE.md adds up (and is still true)
# --------------------------------------------------------------------------

# "603 tests green — 587 Python (`pytest`) and 16 JS (`cd frontend/lib ...`)"
TEST_COUNT_RE = re.compile(
    r"(?P<total>\d+)\s+tests\s+green.*?(?P<py>\d+)\s+Python.*?(?P<js>\d+)\s+JS",
    re.S,
)


def collected_python_tests(root: Path) -> int | None:
    """What pytest actually collects, or None if it could not be asked.

    Collection only -- nothing is executed, so this costs about a second on
    this repo and is worth having: the arithmetic held every one of the three
    times the count was wrong. None (pytest missing, collection erroring) is
    reported as INFO rather than failed: a broken environment is not drifted
    docs, and a lint rule that cries wolf is worse than no rule.
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"^(\d+)\s+tests?\s+collected", proc.stdout, re.M)
    if not match:
        match = re.search(r"^(\d+)/\d+\s+tests?\s+collected", proc.stdout, re.M)
    return int(match.group(1)) if match else None


def rule_test_count(root: Path, *, collect: bool = False) -> list[Problem]:
    """CLAUDE.md's "N tests green — P Python and J JS" must satisfy P+J==N.

    With collect=True, P is also checked against the real collected count.
    Off by default so unit tests can exercise the arithmetic against a
    fixture tree without shelling out.
    """
    text = _read(root, "CLAUDE.md")
    if text is None:
        return [Problem("CLAUDE.md", 0, "missing — nothing states the test count")]
    match = TEST_COUNT_RE.search(text)
    if not match:
        return [
            Problem(
                "CLAUDE.md",
                0,
                'no "N tests green — P Python ... J JS" claim found; either it was '
                "deleted or its wording changed and this rule no longer checks it",
            )
        ]
    line = text[: match.start()].count("\n") + 1
    total, py, js = (int(match.group(k)) for k in ("total", "py", "js"))
    problems: list[Problem] = []
    if py + js != total:
        problems.append(
            Problem(
                "CLAUDE.md",
                line,
                f"{py} Python + {js} JS = {py + js}, not the claimed {total}",
            )
        )
    if collect:
        real = collected_python_tests(root)
        if real is None:
            print("  INFO  could not ask pytest for a collected count; arithmetic only")
        elif real != py:
            problems.append(
                Problem("CLAUDE.md", line, f"claims {py} Python tests; pytest collects {real}")
            )
    return problems


# --------------------------------------------------------------------------
# rule 2 -- every relative markdown link resolves
# --------------------------------------------------------------------------


def rule_links(root: Path) -> list[Problem]:
    """Relative links in CLAUDE.md and docs/*.md must point at real files.

    This is the rename catcher. Absolute URLs and bare anchors are somebody
    else's problem; a link into the tree is this repo's.
    """
    targets = [root / "CLAUDE.md", *sorted((root / "docs").glob("*.md"))]
    problems: list[Problem] = []
    for path in targets:
        text = _read(root, str(path.relative_to(root)))
        if text is None:
            continue
        for lineno, line in enumerate(strip_code(text), start=1):
            for m in _LINK.finditer(line):
                target = m.group("target")
                if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith(("#", "//")):
                    continue
                bare = target.split("#", 1)[0].split("?", 1)[0]
                if not bare:
                    continue
                resolved = (path.parent / bare).resolve()
                if not resolved.exists():
                    problems.append(
                        Problem(
                            str(path.relative_to(root)),
                            lineno,
                            f"link target does not exist: {target}",
                        )
                    )
    return problems


# --------------------------------------------------------------------------
# rule 3 -- no wikilinks anywhere
# --------------------------------------------------------------------------


def rule_no_wikilinks(root: Path) -> list[Problem]:
    """`[[Page]]` renders as literal brackets on GitHub (docs/README.md).

    Obsidian is configured to write standard links; this catches the ones a
    hand or a different editor writes anyway. Code spans are exempt so the
    convention can quote the thing it forbids.
    """
    problems: list[Problem] = []
    for path in markdown_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(strip_code(text), start=1):
            if "[[" in line:
                problems.append(
                    Problem(
                        str(path.relative_to(root)),
                        lineno,
                        "wikilink — GitHub renders it as literal brackets; use [NAME.md](NAME.md)",
                    )
                )
    return problems


# --------------------------------------------------------------------------
# rule 4 -- SERVED_PAGES and the pages CLAUDE.md claims agree
# --------------------------------------------------------------------------

_PAGE_RE = re.compile(r"/app/[A-Za-z0-9_./-]*")


def served_pages_from_skin(root: Path) -> tuple[list[str], Problem | None]:
    """The SERVED_PAGES tuple, read with `ast` rather than imported.

    Canonical since Aug 21. It lived in tests/test_navigation.py and was
    copied into scripts/verify_live.py, and the copy drifted the first
    time a page was added: /app/scoring reached the unit test and not the
    watchdog, so the new page's way home was never checked live.
    """
    rel = "app/feeds/skin.py"
    text = _read(root, rel)
    if text is None:
        return [], Problem(rel, 0, "missing — the served-page list cannot be checked")
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [], Problem(rel, exc.lineno or 0, f"does not parse: {exc.msg}")
    for node in tree.body:
        # Annotated (`SERVED_PAGES: tuple[str, ...] = (...)`) as well as plain.
        named = (
            any(isinstance(t, ast.Name) and t.id == "SERVED_PAGES" for t in node.targets)
            if isinstance(node, ast.Assign)
            else isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "SERVED_PAGES"
        )
        if named and getattr(node, "value", None) is not None:
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                return [], Problem(rel, node.lineno, "SERVED_PAGES is not a literal")
            return [str(v) for v in value], None
    return [], Problem(rel, 0, "no SERVED_PAGES assignment found")


def pages_claimed_in_claude_md(root: Path) -> set[str]:
    """Every `/app/...` page CLAUDE.md names.

    Assets are excluded by the dot in their name (`/app/teams.css`,
    `/app/data/feeds.json`): those are served, but they are not pages with a
    way back to the app, which is what the navigation list is about. `/app/`
    itself is the destination, not an entry.
    """
    text = _read(root, "CLAUDE.md") or ""
    found = set()
    for raw in _PAGE_RE.findall(text):
        page = raw.rstrip("/.,;:)`")
        if page in ("/app", "/app/") or "." in page.rsplit("/", 1)[-1]:
            continue
        found.add(page)
    return found


def rule_served_pages(root: Path) -> list[Problem]:
    """A page in one list and not the other is the drift.

    CLAUDE.md's own rule: "add a page, add it to that list". The list is
    `skin.SERVED_PAGES`; the prose is CLAUDE.md.
    """
    listed, err = served_pages_from_skin(root)
    if err:
        return [err]
    claimed = pages_claimed_in_claude_md(root)
    problems: list[Problem] = []
    for page in sorted(set(listed) - claimed):
        problems.append(
            Problem(
                "CLAUDE.md",
                0,
                f"{page} is in SERVED_PAGES but CLAUDE.md never names it",
            )
        )
    for page in sorted(claimed - set(listed)):
        problems.append(
            Problem(
                "app/feeds/skin.py",
                0,
                f"CLAUDE.md names {page} but it is not in SERVED_PAGES",
            )
        )
    return problems


# --------------------------------------------------------------------------
# rule 5 -- league facts in docs/LEAGUES.md match app/leagues.py
# --------------------------------------------------------------------------

_LEAGUE_HEADING = re.compile(r"^##\s+(?P<title>.+?)\s*$")
_TEAMS_ROW = re.compile(r"^\|\s*Teams\s*\|\s*(?P<teams>[^|]*?)\s*\|")
_ID = re.compile(r"(?:nfl\.l\.)?(?P<id>\d{5,})")


@dataclass(frozen=True)
class DocLeague:
    name: str
    league_id: str | None
    teams: int | None
    line: int


def leagues_from_doc(root: Path) -> tuple[list[DocLeague], Problem | None]:
    """Every `##` section of docs/LEAGUES.md that carries a `| Teams |` row.

    The Teams row is what makes a section a league: "What this means for the
    product" has no such row and is skipped without needing a name list.
    """
    rel = "docs/LEAGUES.md"
    text = _read(root, rel)
    if text is None:
        return [], Problem(rel, 0, "missing — league facts cannot be checked")
    out: list[DocLeague] = []
    current: tuple[str, int] | None = None
    teams: int | None = None
    lines = text.splitlines()

    def flush() -> None:
        if current and teams is not None:
            title, lineno = current
            name = re.split(r"\s+[—–-]\s+", title)[0].strip().strip("`*")
            ident = _ID.search(title)
            out.append(DocLeague(name, ident.group("id") if ident else None, teams, lineno))

    for lineno, line in enumerate(lines, start=1):
        head = _LEAGUE_HEADING.match(line)
        if head:
            flush()
            current, teams = (head.group("title"), lineno), None
            continue
        row = _TEAMS_ROW.match(line)
        if row and current and teams is None:
            digits = re.search(r"\d+", row.group("teams"))
            teams = int(digits.group()) if digits else None
    flush()
    return out, None


def load_leagues_module(root: Path):
    """Import app/leagues.py by path -- it is stdlib-only, so this is safe.

    Importing beats regexing the numbers out: `teams=12` is the value the app
    actually drafts at, whatever a comment beside it says.
    """
    name = "_lint_docs_leagues"
    spec = importlib.util.spec_from_file_location(name, root / "app" / "leagues.py")
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    # Registered before exec: @dataclass reaches back through sys.modules for
    # the defining module's globals, and a module missing from it fails with
    # a bare AttributeError on None.
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


def rule_league_facts(root: Path) -> list[Problem]:
    """Names and team counts in docs/LEAGUES.md must match app/leagues.py.

    The Yahoo league ids are checked doc-to-doc instead: `app/leagues.py`
    deliberately carries none (it is the scoring shape; the keys live in
    `app/config.py`), so the only other place an id is asserted is CLAUDE.md.
    """
    doc_leagues, err = leagues_from_doc(root)
    if err:
        return [err]
    try:
        module = load_leagues_module(root)
    except Exception as exc:  # noqa: BLE001 - any import failure is the finding
        return [Problem("app/leagues.py", 0, f"could not be imported: {type(exc).__name__}: {exc}")]
    if module is None or not hasattr(module, "DEFAULTS"):
        return [Problem("app/leagues.py", 0, "no DEFAULTS tuple of built-in leagues")]

    code = {league.name.upper(): league for league in module.DEFAULTS}
    claude = _read(root, "CLAUDE.md") or ""
    problems: list[Problem] = []
    for doc in doc_leagues:
        league = code.get(doc.name.upper())
        if league is None:
            problems.append(
                Problem(
                    "docs/LEAGUES.md",
                    doc.line,
                    f"{doc.name} is documented but is not a built-in in app/leagues.py",
                )
            )
            continue
        if doc.teams != league.teams:
            problems.append(
                Problem(
                    "docs/LEAGUES.md",
                    doc.line,
                    f"{doc.name} documented as {doc.teams}-team; "
                    f"app/leagues.py drafts it at {league.teams}",
                )
            )
        if doc.league_id and doc.league_id not in claude:
            problems.append(
                Problem(
                    "CLAUDE.md",
                    0,
                    f"{doc.name}'s id {doc.league_id} (docs/LEAGUES.md) is not stated in CLAUDE.md",
                )
            )
    documented = {d.name.upper() for d in doc_leagues}
    for name in sorted(set(code) - documented):
        problems.append(
            Problem(
                "docs/LEAGUES.md",
                0,
                f"{code[name].name} is a built-in in app/leagues.py but has no section here",
            )
        )
    return problems


# --------------------------------------------------------------------------
# rule 6 -- design pages are not linked as if they were built
# --------------------------------------------------------------------------

DESIGN_MARKERS = ("status: design", "planning only", "not built", "nothing here is built")
CAVEAT_WORDS = ("design", "planning", "not built", "not yet", "proposed", "unbuilt", "phase 4")


def design_docs(root: Path) -> dict[str, int]:
    """Docs declaring themselves unbuilt in their first five lines.

    Narrow on purpose: only the exact phrases `docs/README.md` prescribes
    ("Design pages say so in the first line"), only in the header, so a page
    that merely discusses a design is not swept up.
    """
    found: dict[str, int] = {}
    for path in sorted((root / "docs").glob("*.md")):
        head = path.read_text(encoding="utf-8", errors="replace").splitlines()[:5]
        for offset, line in enumerate(head, start=1):
            low = line.lower()
            if any(marker in low for marker in DESIGN_MARKERS):
                found[str(path.relative_to(root))] = offset
                break
    return found


def _paragraphs(text: str) -> list[tuple[int, str]]:
    """(first line number, text) for each blank-line-separated block."""
    blocks: list[tuple[int, str]] = []
    start, buf = 1, []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            if not buf:
                start = lineno
            buf.append(line)
        elif buf:
            blocks.append((start, "\n".join(buf)))
            buf = []
    if buf:
        blocks.append((start, "\n".join(buf)))
    return blocks


def rule_design_pages(root: Path) -> list[Problem]:
    """A link from CLAUDE.md to an unbuilt page must say so where it links.

    The fuzzy version of this rule -- "must not be linked as if implemented"
    -- would cry wolf, and this repo's no-false-positives rule forbids that.
    So it is narrowed to something mechanical: the paragraph carrying the
    link has to contain one of a small set of caveat words. CLAUDE.md's
    PRODUCTIZE.md link passes today because that paragraph says "Planning
    only"; strip the caveat and the rule fires.
    """
    marked = design_docs(root)
    if not marked:
        return []
    text = _read(root, "CLAUDE.md")
    if text is None:
        return []
    problems: list[Problem] = []
    for start, block in _paragraphs(text):
        low = block.lower()
        if any(word in low for word in CAVEAT_WORDS):
            continue
        for m in _LINK.finditer(block):
            target = m.group("target").split("#", 1)[0]
            rel = str(Path(target)) if not target.startswith(("http", "/")) else target
            if rel in marked:
                problems.append(
                    Problem(
                        "CLAUDE.md",
                        start + block[: m.start()].count("\n"),
                        f"links {rel}, which declares itself unbuilt on line {marked[rel]}, "
                        "with no design/planning caveat in the paragraph",
                    )
                )
    return problems


# --------------------------------------------------------------------------
# runner
# --------------------------------------------------------------------------


def rule_one_served_page_list(root: Path) -> list[Problem]:
    """Nobody keeps a second copy of the served-page list.

    This rule exists because the duplicate was not hypothetical: the list
    was copied into the watchdog, /app/scoring was added to one and not
    the other, and the new page shipped with its way home unverified
    live. A rule that only compares prose to code would not have caught
    it — both copies were code.
    """
    problems: list[Problem] = []
    for rel in ("tests/test_navigation.py", "scripts/verify_live.py"):
        text = _read(root, rel)
        if text is None:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            value = getattr(node, "value", None)
            targets = getattr(node, "targets", None) or (
                [node.target] if isinstance(node, ast.AnnAssign) else []
            )
            if not any(isinstance(t, ast.Name) and t.id == "SERVED_PAGES" for t in targets):
                continue
            if isinstance(value, ast.Tuple | ast.List):
                problems.append(
                    Problem(
                        rel,
                        node.lineno,
                        "defines its own SERVED_PAGES literal — read skin.SERVED_PAGES instead",
                    )
                )
        # Either route to the canonical file counts: importing `skin` and
        # reading the attribute, or parsing `skin.py` with `ast`. The
        # watchdog must do the second -- it runs with nothing installed,
        # so importing the app package crashes it (docs/GAP_REVIEW.md).
        reads_canonical = "skin.SERVED_PAGES" in text or (
            "SERVED_PAGES" in text and "skin.py" in text
        )
        if not reads_canonical:
            problems.append(
                Problem(rel, 0, "does not read skin.SERVED_PAGES — it must walk the same list")
            )
    return problems


RULES = (
    ("test count adds up", rule_test_count),
    ("relative links resolve", rule_links),
    ("no wikilinks", rule_no_wikilinks),
    ("served pages agree with SERVED_PAGES", rule_served_pages),
    ("one served-page list, not three", rule_one_served_page_list),
    ("league facts match app/leagues.py", rule_league_facts),
    ("design pages are linked as designs", rule_design_pages),
)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    collect = "--no-collect" not in argv
    argv = [a for a in argv if a != "--no-collect"]
    root = Path(argv[0]).resolve() if argv else REPO_ROOT

    print(f"linting docs in {root}\n")
    failures: list[str] = []
    passed = 0
    total_problems = 0
    for label, rule in RULES:
        problems = rule(root, collect=collect) if rule is rule_test_count else rule(root)
        if problems:
            print(f"  FAIL  {label}")
            for p in problems:
                print(f"          {p}")
            failures.append(label)
            total_problems += len(problems)
        else:
            print(f"  PASS  {label}")
            passed += 1

    plural = "" if total_problems == 1 else "s"
    print(f"\n{passed} passed, {len(failures)} failed, {total_problems} problem{plural}")
    if failures:
        print("\nFAILED rules:")
        for label in failures:
            print(f"  - {label}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
