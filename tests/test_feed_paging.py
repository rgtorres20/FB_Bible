"""Reaching the bottom of a feed and being able to go on.

Owner ask, Aug 22: *"when I get to bottom of Alerts or news, be able to
go to the next page."* Two different problems wearing one sentence.

Alerts already paged at eight a screen — but its only Prev/Next sat
ABOVE the list, so reaching the end meant scrolling back up past
everything just read. News did not page at all: it rendered every item
the overlay carried, which is up to `render.MAX_LIVE_ITEMS` live posts
plus whatever curated rows the wire had not already said.

The paging arithmetic is injected JavaScript, so the strong test is the
one that RUNS it: the slice is extracted from the served page and
executed under node against real list lengths. A test that only matched
strings would pass on code that throws on an empty feed.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from app.feeds import page

INDEX = Path("frontend/index.html")
PAGE_HTML = INDEX.read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _served() -> str:
    out, misses = page.feed_paging(PAGE_HTML)
    assert not misses, f"anchors missed: {misses}"
    return out


def _news_expression(served: str) -> str:
    """The injected News paging block, as an evaluable expression."""
    start = served.index("      ...(() => {\n        const NPAGE = 12;")
    end = served.index("})(),", start) + len("})(),")
    return served[start:end].strip()[3:].rstrip(",")


def _run_news(expr: str, cases: list[tuple[int, int]]) -> list[dict]:
    """Execute the real injected slice under node for each (length, page)."""
    harness = """
const N2 = "n2", N6 = "n6";
const CASES = __CASES__;
const out = CASES.map(([len, wanted]) => {
  const NEWS = Array.from({length: len}, (_, i) =>
    ({kind: i % 2 ? "Post" : "Wire", text: "item" + i}));
  const s = { newsPage: wanted };
  const self = { setState: (o) => Object.assign(s, o) };
  const r = (function () { return __EXPR__; }).call(self);
  return { n: r.news.length, first: r.news.length ? r.news[0].text : null,
           label: r.newsPageLabel, prevDim: r.newsPrevDim, nextDim: r.newsNextDim };
});
console.log(JSON.stringify(out));
"""
    harness = harness.replace("__EXPR__", expr).replace("__CASES__", json.dumps(cases))
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "news_paging.js"
        script.write_text(harness, encoding="utf-8")
        proc = subprocess.run(
            ["node", str(script)], capture_output=True, text=True, timeout=60, check=False
        )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# --- the transform reaches the page ----------------------------------------


def test_every_anchor_fires_against_the_committed_document():
    out, misses = page.feed_paging(PAGE_HTML)
    assert not misses
    assert out != PAGE_HTML


def test_a_page_without_the_anchors_reports_every_miss():
    """Six edits that must land together: a foot pager bound to handlers
    nobody added renders two dead buttons, and a sliced list with no
    pager hides items with no way to reach them."""
    _, misses = page.feed_paging("<html>nothing to patch</html>")
    assert len(misses) == 6


# --- alerts gets a way onward at the foot ----------------------------------


def test_alerts_gains_a_second_pager_at_the_foot_of_the_list():
    served = _served()
    assert served.count("{{ alertNext }}") == 1, "the head pager is left alone"
    assert served.count("{{ alertNextFoot }}") == 1, "and a foot pager is added"
    assert served.count("{{ alertPageLabel }}") == 2, "both say which page this is"


def test_the_foot_pager_scrolls_back_to_the_top_and_the_head_one_does_not():
    """Landing at the bottom of a fresh page is how a pager feels broken
    even when the arithmetic is right. The head pager is already where
    the eye is on arrival, so it must not start moving the page."""
    served = _served()
    head = "alertNext: () => this.setState({ alertPage: Math.min(pages - 1, page + 1) })"
    foot = (
        "alertNextFoot: () => { this.setState({ alertPage: "
        "Math.min(pages - 1, page + 1) }); toTop(); }"
    )
    assert head in served
    assert foot in served


# --- news gets paging at all -----------------------------------------------


def test_news_carries_its_own_page_state():
    served = _served()
    assert "    newsPage: 0," in served, "initialised, or the first page reads undefined"


def test_the_injected_page_script_still_parses():
    """The whole point of injecting JS into someone else's document: a
    broken splice is a blank app, not a failed test."""
    served = _served()
    blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", served, re.S)
    biggest = max(blocks, key=len)
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "page.js"
        script.write_text(biggest, encoding="utf-8")
        proc = subprocess.run(
            ["node", "--check", str(script)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    assert proc.returncode == 0, proc.stderr


def test_news_really_slices_into_pages_of_twelve():
    expr = _news_expression(_served())
    first, third = _run_news(expr, [(40, 0), (40, 2)])
    assert first["n"] == 12 and first["first"] == "item0"
    assert third["n"] == 12 and third["first"] == "item24", "page 3 starts where page 2 ended"
    assert "Page 1 of 4" in first["label"]
    assert "40 posts" in first["label"]


def test_the_first_page_dims_prev_and_the_last_dims_next():
    expr = _news_expression(_served())
    first, last = _run_news(expr, [(40, 0), (40, 3)])
    assert first["prevDim"] == "0.25" and first["nextDim"] == "1"
    assert last["prevDim"] == "1" and last["nextDim"] == "0.25"


def test_a_page_beyond_the_end_clamps_rather_than_rendering_nothing():
    """State outlives the data: a reader parked on page 4 when the wire
    trims back to one page must not get a blank feed."""
    (clamped,) = _run_news(_news_expression(_served()), [(40, 99)])
    assert clamped["n"] == 4, "the real last page, not an empty slice"
    assert "Page 4 of 4" in clamped["label"]


def test_a_short_or_empty_feed_does_not_divide_by_zero():
    """An empty feed is a real state — every source failing at once —
    and it must render page 1 of 1 rather than NaN or a crash."""
    short, empty = _run_news(_news_expression(_served()), [(5, 0), (0, 0)])
    assert short["n"] == 5 and "Page 1 of 1" in short["label"]
    assert empty["n"] == 0 and "Page 1 of 1" in empty["label"]
    assert "NaN" not in empty["label"]
