"""Sleeper season stats: coverage is measured, usage reads are all-or-nothing.

The contract under test comes from the probe that shaped the module: the
endpoint's richest entries are team aggregates, so per-player coverage can
never be assumed -- reduce() must count it, and usage_reads() must refuse to
return a partial map rather than leave fabricated fallbacks standing next to
real numbers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.feeds import stats

PAGE = Path("frontend/index.html").read_text(encoding="utf-8")

# Sleeper's spellings: WAS here, WSH in the page.
SLEEPER_CODES = (
    "ARI",
    "ATL",
    "BAL",
    "BUF",
    "CAR",
    "CHI",
    "CIN",
    "CLE",
    "DAL",
    "DEN",
    "DET",
    "GB",
    "HOU",
    "IND",
    "JAX",
    "KC",
    "LAC",
    "LAR",
    "LV",
    "MIA",
    "MIN",
    "NE",
    "NO",
    "NYG",
    "NYJ",
    "PHI",
    "PIT",
    "SEA",
    "SF",
    "TB",
    "TEN",
    "WAS",
)


def _team_entry(pass_att=582.0, rush_att=475.0, pass_rz=72.0, rush_rz=73.0) -> dict:
    return {
        "gp": 17.0,
        "pass_att": pass_att,
        "rush_att": rush_att,
        "pass_rz_att": pass_rz,
        "rush_rz_att": rush_rz,
        "rz_att": 54.0,
        "rz_conv": 25.0,
        "g2g_att": 28.0,
        "g2g_conv": 19.0,
        "pass_yd": 3956.0,
        "rush_yd": 1852.0,
    }


def _raw(teams: dict[str, dict] | None = None) -> dict:
    """A payload with the endpoint's three populations, real shapes."""
    raw = {
        # Rich player: a rushing QB (the real probe's richest entry shape).
        "11560": {
            "gp": 17.0,
            "pass_att": 568.0,
            "rush_att": 77.0,
            "off_snp": 1088.0,
            "tm_off_snp": 1099.0,
            "rush_rz_att": 20.0,
            "pass_rz_att": 72.0,
        },
        # RB with usage but no passing fields -- coverage must reflect that.
        "4034": {
            "gp": 16.0,
            "rush_att": 260.0,
            "rec_tgt": 55.0,
            "rec": 48.0,
            "off_snp": 601.0,
            "tm_off_snp": 1050.0,
        },
        # IDP: snaps only, no offensive usage -- reduced out of players.
        "7591": {"gp": 17.0, "tm_off_snp": 1000.0, "tm_def_snp": 999.0},
        # Ranked-only entry (most of the 8,179 look like this).
        "9999": {"pos_rank_ppr": 4000},
        # Team defense aggregate under the bare code.
        "HOU": {"gp": 17.0, "sack": 47.0, "pts_allow": 295.0},
    }
    for code in SLEEPER_CODES:
        raw[f"TEAM_{code}"] = dict((teams or {}).get(code) or _team_entry())
    return raw


# --- reduce ----------------------------------------------------------------


def test_reduce_separates_the_three_populations():
    state = stats.reduce(_raw())
    assert state["populations"] == {"players": 4, "team_offense": 32, "team_defense": 1}
    assert state["season"] == 2025


def test_reduce_maps_sleeper_team_codes_to_the_pages():
    state = stats.reduce(_raw())
    assert "WSH" in state["teams"]
    assert "WAS" not in state["teams"]


def test_reduce_keeps_only_players_with_offensive_usage():
    state = stats.reduce(_raw())
    assert set(state["players"]) == {"11560", "4034"}
    # and only the declared fields, so the store stays small
    assert set(state["players"]["4034"]) <= set(stats.PLAYER_FIELDS)


def test_reduce_measures_field_coverage_rather_than_assuming_it():
    cov = stats.reduce(_raw())["coverage"]
    # pass_att: the QB carries it, the RB does not -- 1 of 4 players.
    assert cov["players"]["pass_att"] == 1
    assert cov["players"]["rush_att"] == 2
    assert cov["players"]["rec_tgt"] == 1
    # a declared field nobody carries reports 0, not a KeyError downstream
    assert cov["players"]["rec_rz_tgt"] == 0
    assert cov["team_offense"]["pass_att"] == 32


# --- staleness -------------------------------------------------------------


def test_stale_when_absent_or_old_or_unstamped():
    now = datetime(2026, 8, 16, tzinfo=UTC)
    assert stats.stale(None, now)
    assert stats.stale({}, now)
    fresh = stats.reduce(_raw())
    assert not stats.stale(fresh, datetime.now(UTC))
    old = {**fresh, "fetched_at": (now - timedelta(days=8)).isoformat()}
    assert stats.stale(old, now)
    naive = {**fresh, "fetched_at": "2026-08-16T00:00:00"}
    assert stats.stale(naive, now)


# --- usage reads -----------------------------------------------------------


def test_usage_reads_computes_pass_rate_and_rz_run_share():
    reads = stats.usage_reads(stats.reduce(_raw()))
    assert reads is not None
    hou = reads["HOU"]
    assert hou == {"pass": 55, "rz_run": 50}  # 582/1057, 73/145 -- real '25 HOU


def test_usage_reads_refuses_partial_team_coverage():
    raw = _raw()
    del raw["TEAM_DET"]
    assert stats.usage_reads(stats.reduce(raw)) is None


def test_usage_reads_refuses_a_team_missing_a_field():
    broken = _team_entry()
    del broken["rush_rz_att"]
    state = stats.reduce(_raw(teams={"GB": broken}))
    assert stats.usage_reads(state) is None


def test_usage_reads_handles_no_state():
    assert stats.usage_reads(None) is None
    assert stats.usage_reads({}) is None


# --- serve-time injection --------------------------------------------------


def test_inject_replaces_all_three_consts_and_relabels():
    patched, live = stats.inject(PAGE, stats.reduce(_raw()))
    assert live
    assert patched.count(stats.LIVE_MARKER) == 3
    # every team present in every const, page spelling
    assert '"WSH":' in patched
    # the label now names the stat and its vintage, on both tabs
    assert '"RZ " + (GLRUN' in patched
    assert '"RZ " + (TEAM_SPLIT' in patched
    assert patched.count("% run share ('25)") == 2
    assert '"GL " + (GLRUN' not in patched
    # the run-heavy accent moved to the red-zone scale
    assert "(GLRUN[tm.code] || 0) >= 55" in patched
    assert ">= 68" not in patched


def test_inject_serves_the_committed_page_when_coverage_is_partial():
    raw = _raw()
    del raw["TEAM_DET"]
    patched, live = stats.inject(PAGE, stats.reduce(raw))
    assert not live
    assert patched == PAGE


def test_inject_misses_cleanly_when_the_page_shape_changed():
    patched, live = stats.inject("<html>no consts here</html>", stats.reduce(_raw()))
    assert not live
    assert patched == "<html>no consts here</html>"


# --- Data health stamping --------------------------------------------------


def _one_item() -> dict:
    return {
        "id": "a",
        "source_key": "espn",
        "source_name": "ESPN",
        "tier": 1,
        "title": "Nacua limited",
        "summary": "",
        "published": "2026-08-15T02:00:00+00:00",
        "players": [],
    }


def test_meta_stamps_team_intel_only_when_usage_reads_are_complete():
    from app.feeds import render

    bundled = {
        "news": [],
        "meta": [
            {
                "feed": "Team intel / projections",
                "asOf": "2026-08-12T12:00",
                "source": "'25 stats + win totals (estimates)",
            }
        ],
    }
    now = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)

    state = stats.reduce(_raw())
    # The stamp is the DATA's own fetch time, not the request's -- pin a
    # known one so the assertion says exactly that.
    state["fetched_at"] = "2026-08-16T09:30:00+00:00"
    live = render.merge_into_feeds(bundled, [_one_item()], now, stats_state=state)
    row = live["meta"][0]
    assert "Sleeper '25 season" in row["source"]
    assert "red-zone run share" in row["source"]
    assert "projections still curated" in row["source"]
    assert row["asOf"] == "2026-08-16T04:30"  # the fetch, rendered Central

    partial_raw = _raw()
    del partial_raw["TEAM_DET"]
    stale_meta = render.merge_into_feeds(
        bundled, [_one_item()], now, stats_state=stats.reduce(partial_raw)
    )
    assert stale_meta["meta"][0]["source"] == "'25 stats + win totals (estimates)"


# --- team defenses ----------------------------------------------------------
#
# Owner, Aug 21: "some leagues do Team DEF not just IDP." The 32 bare
# team-code entries were counted and thrown away until then. Two things
# have to hold before anything ranks them: the right keys are read, and
# the points-allowed ladder is checked rather than trusted.


def _defense_entry(**over) -> dict:
    """Detroit's real '25 line (probe run 7, 2026-08-21), trimmed."""
    return {
        "gp": 17.0,
        "sack": 49.0,
        "int": 13.0,
        "ff": 15.0,
        "fum_rec": 6.0,
        "safe": 1.0,
        "fg_blkd": 2.0,
        "def_st_td": 1.0,
        "def_pass_def": 93.0,
        "int_ret_yd": 132.0,
        "fum_ret_yd": 5.0,
        "pts_allow": 411.0,
        "yds_allow": 5642.0,
        "td": 57.0,  # touchdowns ALLOWED -- must never be kept
        "pts_allow_7_13": 2.0,
        "pts_allow_14_20": 2.0,
        "pts_allow_21_27": 8.0,
        "pts_allow_28_34": 4.0,
        "pts_allow_35p": 1.0,
        **over,
    }


def test_reduce_keeps_the_team_defense_lines_it_used_to_discard():
    raw = _raw()
    raw["DET"] = _defense_entry()
    state = stats.reduce(raw)
    det = state["defenses"]["DET"]
    assert det["sack"] == 49.0 and det["def_st_td"] == 1.0
    assert det["pts_allow_21_27"] == 8.0


def test_touchdowns_allowed_never_reach_the_store():
    """`td` on a team-defense entry is what the defense gave up -- 57 for
    Detroit. Keeping it would let a scoring bug turn it into 342 points."""
    raw = _raw()
    raw["DET"] = _defense_entry()
    assert "td" not in stats.reduce(raw)["defenses"]["DET"]


def test_defense_fields_are_read_only_from_the_bare_team_codes():
    """`sack`, `int`, `ff`, `fum_rec` and `qb_hit` appear on the team
    OFFENSE entries too -- as sacks and turnovers *given up*, 64 holders
    across the dump rather than 32 (census, 2026-08-21). Reading them
    from the wrong population would rank offenses as defenses."""
    raw = _raw()
    raw["TEAM_DET"] = {**raw["TEAM_HOU"], "sack": 61.0, "int": 19.0}
    raw["DET"] = _defense_entry()
    state = stats.reduce(raw)
    assert state["defenses"]["DET"]["sack"] == 49.0
    assert "DET" not in {k for k in state["defenses"] if k.startswith("TEAM")}
    # The offense entry keeps its own fields under `teams`, untouched.
    assert "sack" not in set(stats.TEAM_FIELDS)


def test_a_points_allowed_ladder_that_does_not_add_up_is_reported_not_trusted():
    """The check that those buckets are game counts at all. A ladder that
    misses a band would silently underscore that defense, and an
    underscored defense reads as a ranking rather than as a gap."""
    raw = _raw()
    raw["DET"] = _defense_entry()  # 2+2+8+4+1 = 17 = gp
    raw["CLE"] = _defense_entry(pts_allow_35p=0.0)  # 16 of 17 games
    cov = stats.reduce(raw)["coverage"]
    assert cov["defenses"] == 3  # DET, CLE and the fixture's HOU
    assert cov["defense_pa_complete"] == 1


def test_a_stored_blob_without_defenses_is_stale():
    """The version bump alone would do it, but this is the assertion that
    survives the next bump: no defenses means the board cannot rank one,
    so the weekly refetch has to run rather than wait out its window."""
    fresh = stats.reduce(_raw())
    assert not stats.stale(fresh, datetime.now(UTC))
    assert stats.stale({**fresh, "defenses": {}}, datetime.now(UTC))
