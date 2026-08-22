"""The watchdog must run on a bare runner, with nothing installed.

`scripts/verify_live.py` checks a live deployment. Its whole value is
being able to do that without building an environment first, so the
workflow that runs it does a checkout and nothing else — no pip install.

That property is invisible in CI, which installs everything, and it broke
exactly the way you would expect: centralising the served-page list on
Aug 21 turned one line into `from app.feeds import skin`, which pulls in
`app/feeds/__init__.py`, which imports the poller, which imports httpx.
The watchdog died one second in, before a single check ran, and the run
before it had been green — so nothing but reading the log said so.

Hence this: a static check that nothing outside the standard library is
imported. Static rather than "import it and see", because importing it
here would pass on this machine for the same reason CI did.
"""

from __future__ import annotations

import ast
import pathlib
import sys

WATCHDOG = pathlib.Path("scripts/verify_live.py")


def _imported_roots(path: pathlib.Path) -> set[str]:
    """Top-level package names this module imports, at any depth."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_the_watchdog_imports_only_the_standard_library():
    outside = sorted(_imported_roots(WATCHDOG) - sys.stdlib_module_names - {"__future__"})
    assert not outside, (
        f"scripts/verify_live.py imports {outside}, which the runner does not install — "
        "it does a checkout and nothing else"
    )


def test_the_watchdog_does_not_import_the_app():
    """The specific failure, named. `app.feeds` is not merely a dependency
    — importing any part of it executes `app/feeds/__init__.py`, which
    reaches for httpx before the script's first line runs."""
    assert "app" not in _imported_roots(WATCHDOG)


def test_the_watchdog_still_reads_the_canonical_page_list():
    """Being standalone must not be bought by keeping a second copy — that
    was the bug centralising the list fixed. It reads skin.py as a file."""
    source = WATCHDOG.read_text(encoding="utf-8")
    assert "SERVED_PAGES" in source
    assert "skin.py" in source, "it should read the canonical file, not a copy"


def test_the_watchdog_reads_the_same_pages_the_app_serves():
    """End to end: whatever the ast reader pulls out has to equal what the
    app itself declares. A reader that silently returned an empty tuple
    would make every navigation check vanish and the run still pass."""
    from app.feeds import skin

    namespace: dict = {"__file__": str(WATCHDOG.resolve())}
    tree = ast.parse(WATCHDOG.read_text(encoding="utf-8"))
    # Just the preamble: imports, REPO_ROOT, the reader, and its call.
    cut = next(
        i
        for i, node in enumerate(tree.body)
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", "") == "SERVED_PAGES" for t in node.targets)
    )
    exec(compile(ast.Module(tree.body[: cut + 1], []), "verify_live", "exec"), namespace)
    assert namespace["SERVED_PAGES"] == skin.SERVED_PAGES
    assert len(namespace["SERVED_PAGES"]) == 11
