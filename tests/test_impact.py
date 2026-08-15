"""Impact scoring and dedupe tests.

Each scenario is a real item from the Aug 15 live feed, not an invention --
the module exists because these exact items were handled badly.
"""

from datetime import UTC, datetime

from app.feeds import impact

NOW = datetime(2026, 8, 15, 6, 0, tzinfo=UTC)

RANKS = {"nacua": 4, "bijan": 1, "tua": 200, "brady": None, "allar": 389}


def item(title, summary="", players=None, source="ESPN NFL", tier=1, published=None):
    return {
        "title": title,
        "summary": summary,
        "players": players or [],
        "source_name": source,
        "tier": tier,
        "published": published or "2026-08-15T05:00:00+00:00",
    }


NACUA = {"id": "nacua", "name": "Puka Nacua", "position": "WR", "team": "LAR"}
BRADY = {"id": "brady", "name": "Tom Brady", "position": "QB", "team": None}
TUA = {"id": "tua", "name": "Tua Tagovailoa", "position": "QB", "team": "ATL"}
PEARCE = {"id": "pearce", "name": "James Pearce Jr.", "position": "LB", "team": "ATL"}


# --- classification --------------------------------------------------------


def test_torn_acl_is_severe():
    assert impact.classify("Cards rookie OL has torn MCL") == "severe"


def test_suspension_is_severe():
    assert impact.classify("Falcons' Pearce suspended 8 games after arrest") == "severe"


def test_day_to_day_is_status():
    assert impact.classify("Geno Smith has sore ankle, considered day-to-day") == "status"


def test_returning_to_practice_is_positive():
    assert impact.classify("Nacua expected back at practice next week") == "positive"


def test_broadcast_story_is_noise():
    assert impact.classify("Aikman gets Brady-like limits for MNF broadcasts") == "noise"


def test_severe_beats_positive_in_the_same_sentence():
    text = "Cleared for contact but placed on injured reserve"
    assert impact.classify(text) == "severe"


def test_plain_football_news_is_uncategorised():
    assert impact.classify("Panthers acquire backup lineman from Jets") is None


def test_a_debut_is_deliberately_positive():
    """ "Tua debuts for ATL" is fantasy-relevant news, not noise."""
    assert impact.classify("Two drives, two punts in Falcons debut") == "positive"


# --- scoring ---------------------------------------------------------------


def test_the_tom_brady_case_scores_negative():
    """The live failure this exists for: correct name match on a broadcasting
    story about a free agent."""
    scored = impact.score(
        item("Aikman gets Brady-like limits for MNF broadcasts", players=[BRADY]), RANKS
    )
    assert scored["impact_score"] < 0


def test_injury_to_a_top_player_scores_high():
    scored = impact.score(
        item("Nacua leaves practice with hamstring injury", players=[NACUA]), RANKS
    )
    assert scored["impact_score"] >= 65  # status 25 + top-100 rank 40
    assert scored["impact_category"] == "status"
    assert scored["top_rank"] == 4


def test_same_injury_to_a_fringe_player_scores_lower():
    fringe = {"id": "allar", "name": "Drew Allar", "position": "QB", "team": "PIT"}
    star = impact.score(item("X leaves with hamstring injury", players=[NACUA]), RANKS)
    scrub = impact.score(item("X leaves with hamstring injury", players=[fringe]), RANKS)
    assert star["impact_score"] > scrub["impact_score"]


def test_untagged_league_news_is_slightly_negative_without_keywords():
    scored = impact.score(item("Owners approve new stadium financing"), RANKS)
    assert scored["impact_score"] < 0  # noise keyword + no players


def test_missing_rank_map_still_scores_on_keywords():
    scored = impact.score(item("Nacua ruled out for the season", players=[NACUA]), None)
    assert scored["impact_score"] >= 50
    assert scored["top_rank"] is None


# --- annotation ------------------------------------------------------------


def test_annotation_is_factual_and_marked_auto():
    scored = impact.score(item("Nacua ruled out", players=[NACUA]), RANKS)
    note = impact.annotate(scored)
    assert note.startswith("Auto:")
    assert "Puka Nacua" in note
    assert "top-100" in note


def test_no_annotation_for_noise():
    scored = impact.score(item("Stadium financing approved"), RANKS)
    assert impact.annotate(scored) == ""


# --- dedupe ----------------------------------------------------------------


def test_same_headline_from_two_outlets_folds_into_one():
    """The Pearce suspension arrived from ESPN, Yahoo and CBS."""
    a = impact.score(
        item(
            "Falcons' Pearce suspended 8 games after arrest",
            players=[PEARCE],
            source="ESPN NFL",
            tier=1,
        ),
        RANKS,
    )
    b = impact.score(
        item(
            "Falcons LB Pearce suspended 8 games by NFL",
            players=[PEARCE],
            source="Yahoo Sports NFL",
            tier=1,
        ),
        RANKS,
    )
    c = impact.score(
        item(
            "Pearce banned 8 games after arrest", players=[PEARCE], source="CBS Sports NFL", tier=2
        ),
        RANKS,
    )

    clustered = impact.cluster([a, b, c])

    assert len(clustered) == 1
    assert clustered[0]["source_name"] == "ESPN NFL"
    assert set(clustered[0]["also_from"]) == {"Yahoo Sports NFL", "CBS Sports NFL"}


def test_different_stories_about_the_same_player_stay_separate():
    a = impact.score(item("Tua frustrated by preseason performance", players=[TUA]), RANKS)
    b = impact.score(item("Tua exits with ankle injury", players=[TUA]), RANKS)
    # One is uncategorised, one is status -- different events, both kept.
    assert len(impact.cluster([a, b])) == 2


def test_a_tier1_telling_replaces_a_tier2_one():
    a = impact.score(
        item("Pearce suspended 8 games", players=[PEARCE], source="CBS Sports NFL", tier=2), RANKS
    )
    b = impact.score(
        item("Pearce suspended 8 games after arrest", players=[PEARCE], source="ESPN NFL", tier=1),
        RANKS,
    )
    clustered = impact.cluster([a, b])
    assert len(clustered) == 1
    assert clustered[0]["tier"] == 1
    assert "CBS Sports NFL" in clustered[0]["also_from"]


def test_stories_far_apart_in_time_do_not_fold():
    a = impact.score(
        item("Nacua hamstring injury", players=[NACUA], published="2026-08-10T00:00:00+00:00"),
        RANKS,
    )
    b = impact.score(
        item("Nacua hamstring injury", players=[NACUA], published="2026-08-15T00:00:00+00:00"),
        RANKS,
    )
    assert len(impact.cluster([a, b])) == 2


def test_cluster_does_not_mutate_its_input():
    a = impact.score(item("Pearce suspended", players=[PEARCE], source="ESPN NFL"), RANKS)
    b = impact.score(
        item("Pearce suspended", players=[PEARCE], source="CBS Sports NFL", tier=2), RANKS
    )
    impact.cluster([a, b])
    assert "also_from" not in a


# --- reading order ---------------------------------------------------------


def _scored(score, published, title="t"):
    return {"title": title, "impact_score": score, "published": published}


def test_order_puts_high_impact_above_newer_routine_news():
    routine = _scored(0, "2026-08-15T05:00:00+00:00", "fresh nothing")
    severe = _scored(50, "2026-08-13T05:00:00+00:00", "two-day-old ACL")
    assert [i["title"] for i in impact.order([routine, severe], NOW)] == [
        "two-day-old ACL",
        "fresh nothing",
    ]


def test_order_decays_old_stories_beneath_fresh_ones():
    """Three weeks of decay outweighs a severe score: draft-day reading
    should not open on the same suspension for a month."""
    stale = _scored(50, "2026-07-26T05:00:00+00:00", "20-day-old suspension")
    fresh = _scored(0, "2026-08-15T05:00:00+00:00", "this morning")
    assert impact.order([stale, fresh], NOW)[0]["title"] == "this morning"


def test_order_breaks_ties_newest_first():
    older = _scored(25, "2026-08-15T01:00:00+00:00", "older")
    newer = _scored(25, "2026-08-15T05:00:00+00:00", "newer")
    assert [i["title"] for i in impact.order([older, newer], NOW)] == ["newer", "older"]


def test_order_treats_undated_items_as_a_week_old():
    undated = _scored(25, None, "undated")
    dated_week = _scored(25, "2026-08-08T05:00:00+00:00", "a week old")
    fresh = _scored(25, "2026-08-15T05:00:00+00:00", "fresh")
    ordered = [i["title"] for i in impact.order([undated, fresh, dated_week], NOW)]
    assert ordered[0] == "fresh"
    assert set(ordered[1:]) == {"undated", "a week old"}
