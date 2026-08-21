"""Unit fences, enforced.

Owner, Aug 21: break the product into parts agents can work on without
knowing the whole project. A part is only ownable if it has a fence —
what it may import — and a fence written only in a doc erodes on the
first convenient import. So the fence is a test, the same trick as
`tests/test_navigation.py`.

The model is a layer stack, measured from the real import graph rather
than invented:

    kernel    shared contracts. Anyone may import these. Changing one is
              a reviewed decision, not a side effect of a feature.
    data      units that own a source and produce a documented shape.
              Pure transforms; an agent can own one knowing nothing else.
    surface   units that own a page. They compose data units — that is
              their whole job, so importing downward is not a breach.
    composer  main.py and the routes: assembling units *is* the job.

Two rules follow, and both are about direction:

  1. Nothing imports upward. A data unit reaching into a surface inverts
     the stack and drags a page's concerns into a transform.
  2. Data units do not import each other sideways. Two units that know
     about each other cannot be owned separately, which was the point.

Plus one rule that is not about layers at all: **no module touches
another module's private names.** A leading underscore is a promise that
the symbol can change without warning; crossing that line couples you to
something nobody agreed to keep stable.

KNOWN_BREACHES is a ratchet. The test asserts the current breach set is
*exactly* this set — so a new breach fails, and fixing a listed one also
fails until the entry is deleted. It can only shrink.
"""

from __future__ import annotations

import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

KERNEL = frozenset(
    {
        "config", "leagues", "store", "skin", "teams", "players", "crypto",
        "deps", "base", "file_store", "redis_store", "sources", "parse",
        "oauth", "client", "authn", "passkeys", "mailer",
    }
)  # fmt: skip

COMPOSERS = frozenset({"main", "feeds", "league", "leaguecfg", "userdata", "access", "auth"})

DATA_UNITS: dict[str, frozenset[str]] = {
    "wire": frozenset({"poller", "rss", "rotoworld", "impact", "injury"}),
    "adp": frozenset({"adp", "board", "ranklists"}),
    "usage": frozenset({"stats", "depth"}),
    "odds": frozenset({"vegas"}),
    "ai": frozenset({"capsules", "previews", "weekrev"}),
    "scoring": frozenset({"scorecard"}),
}

SURFACES = frozenset(
    {
        "page",
        "render",
        "idp",
        "mock",
        "nextup",
        "topscorers",
        "accuracy",
        "cheatsheet",
        "alerts300",
    }
)

UNIT_OF = {mod: unit for unit, mods in DATA_UNITS.items() for mod in mods}
LAYER = (
    {m: 0 for m in KERNEL}
    | {m: 1 for m in UNIT_OF}
    | {m: 2 for m in SURFACES}
    | {m: 3 for m in COMPOSERS}
)

# Every breach that exists today, with why it is here and what fixing it
# would take. Delete an entry when you fix it — the test will tell you.
KNOWN_BREACHES = frozenset(
    {
        # capsules needs one time formatter that happens to live in a page
        # module. Fix: move `render.format_time` into the kernel.
        "capsules imports render (upward: data -> surface)",
        # Both want facts that are not really odds. scorecard wants the
        # season year; previews wants implied totals and a game-string
        # regex. Fix: lift the season constant to config, and give vegas a
        # public accessor for the matchup parse.
        "previews imports vegas (sideways: ai -> odds)",
        "scorecard imports vegas (sideways: scoring -> odds)",
        # The regex is private. This is the sharpest of the three: it
        # couples previews to a name vegas never promised to keep.
        "previews touches private vegas._GAME_TEAMS",
    }
)


def _modules() -> list[pathlib.Path]:
    return sorted(p for p in APP.rglob("*.py") if "__pycache__" not in str(p))


def _tree(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _internal_imports(tree: ast.Module) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (
            node.level or (node.module or "").startswith("app")
        ):
            for alias in node.names:
                found.add(alias.name)
    return found


def _private_reaches(tree: ast.Module, known: set[str]) -> set[tuple[str, str]]:
    """`other._THING` where `other` is another module we imported."""
    hits: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in known
            and node.attr.startswith("_")
            and not node.attr.startswith("__")
        ):
            hits.add((node.value.id, node.attr))
    return hits


def _breaches() -> set[str]:
    found: set[str] = set()
    for path in _modules():
        name = path.stem
        if name == "__init__" or name in COMPOSERS:
            continue
        tree = _tree(path)
        imported = _internal_imports(tree)

        for other in imported:
            if other == name:
                continue
            here, there = LAYER.get(name), LAYER.get(other)
            if here is not None and there is not None and there > here:
                found.add(
                    f"{name} imports {other} (upward: "
                    f"{'data' if here == 1 else 'surface'} -> "
                    f"{'surface' if there == 2 else 'composer'})"
                )
            unit, other_unit = UNIT_OF.get(name), UNIT_OF.get(other)
            if unit and other_unit and unit != other_unit:
                found.add(f"{name} imports {other} (sideways: {unit} -> {other_unit})")

        for other, attr in _private_reaches(tree, imported):
            if other != name:
                found.add(f"{name} touches private {other}.{attr}")
    return found


def test_every_module_is_classified():
    """A new module lands in the kernel, a data unit, a surface or the
    composers — never nowhere. Forgetting to classify it is how the fence
    quietly stops covering anything."""
    unclassified = [
        str(p.relative_to(APP.parent))
        for p in _modules()
        if p.stem != "__init__" and p.stem not in LAYER
    ]
    assert not unclassified, (
        f"Unclassified modules — add each to KERNEL, DATA_UNITS, SURFACES "
        f"or COMPOSERS in this file: {unclassified}"
    )


def test_no_new_boundary_breaches():
    """The fence. New coupling fails here."""
    new = _breaches() - KNOWN_BREACHES
    assert not new, (
        "New boundary breach. Route the data through a composer, or lift the "
        f"shared thing into the kernel: {sorted(new)}"
    )


def test_known_breaches_still_exist():
    """The other side of the ratchet. Fix one and this fails until you
    delete its entry — so the list can only ever shrink, and it can never
    quietly describe a problem that is no longer there."""
    stale = KNOWN_BREACHES - _breaches()
    assert not stale, f"These breaches are fixed — delete them from KNOWN_BREACHES: {sorted(stale)}"


def test_the_kernel_depends_on_nothing_above_it():
    """The kernel is what everyone may import, so it must sit underneath
    everything. A kernel module importing a unit inverts that and makes
    every unit transitively own every other."""
    breaches = [
        f"kernel module {p.stem} imports {other}"
        for p in _modules()
        if p.stem in KERNEL
        for other in _internal_imports(_tree(p))
        if LAYER.get(other, 0) > 0
    ]
    assert not breaches, breaches


def test_the_layers_do_not_overlap():
    """A module in two layers is a fence with a hole in it."""
    groups = {"kernel": set(KERNEL), "surface": set(SURFACES), "composer": set(COMPOSERS)}
    groups |= {f"data:{u}": set(m) for u, m in DATA_UNITS.items()}
    names = sorted(groups)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            overlap = groups[a] & groups[b]
            assert not overlap, f"{a} and {b} both claim {sorted(overlap)}"
