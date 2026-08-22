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


def test_the_earliest_telling_survives_the_fold():
    """Owner, Aug 21: "just needs to log info first and add to the list."
    Whoever reported it first is the telling that survives; the rest are
    credited. Being first is a fact, unlike being the outlet we rate
    highest -- wire sources carry no weight (docs/WEIGHTS.md)."""
    early = impact.score(
        item(
            "Pearce suspended 8 games",
            players=[PEARCE],
            source="CBS Sports NFL",
            tier=2,
            published="2026-08-15T05:00:00+00:00",
        ),
        RANKS,
    )
    late = impact.score(
        item(
            "Pearce suspended 8 games after arrest",
            players=[PEARCE],
            source="ESPN NFL",
            tier=1,
            published="2026-08-15T09:00:00+00:00",
        ),
        RANKS,
    )
    for order in ([early, late], [late, early]):
        clustered = impact.cluster(order)
        assert len(clustered) == 1
        # The later, better-tier ESPN telling must NOT win.
        assert clustered[0]["source_name"] == "CBS Sports NFL"
        assert clustered[0]["also_from"] == ["ESPN NFL"]


def test_an_undated_telling_never_wins_by_having_no_time():
    """An item with no date must not beat a dated one to the front. It has
    no claim to being first -- it has no claim at all."""
    dated = impact.score(
        item("Pearce suspended 8 games", players=[PEARCE], source="ESPN NFL"), RANKS
    )
    undated = impact.score(
        item("Pearce suspended 8 games after arrest", players=[PEARCE], source="CBS Sports NFL"),
        RANKS,
    )
    undated["published"] = None
    clustered = impact.cluster([undated, dated])
    assert len(clustered) == 1
    assert clustered[0]["source_name"] == "ESPN NFL"


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


def test_rank_boundaries_label_the_right_band():
    """Rank 100 is a top-100 player; the old arithmetic called him top-200."""
    scored = {"players": [NACUA], "impact_category": "severe", "top_rank": 100}
    assert "top-100" in impact.annotate(scored)
    scored["top_rank"] = 400
    assert "top-400" in impact.annotate(scored)


def test_the_fold_never_credits_the_surviving_outlet_to_itself():
    """ "ESPN (also: ESPN, CBS)" credits nobody. The winner's own name must
    never appear in the list of who else carried it."""
    tellings = [
        impact.score(
            item(
                "Pearce suspended 8 games",
                players=[PEARCE],
                source=src,
                published=f"2026-08-15T{hour:02d}:00:00+00:00",
            ),
            RANKS,
        )
        for src, hour in (("ESPN NFL", 9), ("CBS Sports NFL", 5), ("Yahoo Sports NFL", 11))
    ]
    clustered = impact.cluster(tellings)
    assert len(clustered) == 1
    winner = clustered[0]
    assert winner["source_name"] == "CBS Sports NFL"
    assert winner["source_name"] not in winner["also_from"]
    assert sorted(winner["also_from"]) == ["ESPN NFL", "Yahoo Sports NFL"]


def test_naive_published_stamp_does_not_crash_clustering():
    """One publisher drifting to naive ISO must not 500 the overlay."""
    aware = item("Pearce suspended 8 games", players=[PEARCE])
    naive = item(
        "Falcons LB Pearce suspended 8 games", players=[PEARCE], published="2026-08-15T05:00:00"
    )
    kept = impact.cluster([impact.score(aware), impact.score(naive)])
    assert len(kept) == 1  # same player, same category: still folds


def test_every_word_for_a_player_being_kept_off_the_field_is_severe():
    """A suspension, a ban and an ineligibility ruling are the same event
    for a draft board: the player is not playing. They arrive worded
    differently from different outlets, and a headline that lands in a
    *different* bucket than its twin cannot fold with it -- the same-player
    fold is gated on both tellings sharing a category, so one word missing
    from this bucket is two rows about one story instead of one."""
    for text in (
        "Falcons' Pearce suspended 8 games after arrest",
        "Pearce banned 8 games by the NFL",
        "Pearce barred from team activities pending review",
        "Pearce ruled ineligible for the 2026 season",
    ):
        assert impact.classify(text) == "severe", text


def test_a_possessive_team_name_tokenises_the_same_as_a_plain_one():
    """Outlets differ on "Falcons' Pearce" vs "Falcons Pearce", and the
    fold compares word sets. A trailing apostrophe left on the token
    makes the two spellings disagree on every mention of the team, which
    drags the overlap under the threshold and splits one story in two."""
    assert impact._tokens("Jets' Hall carted off") == impact._tokens("Jets Hall carted off")
    # The apostrophe inside a name is not punctuation to be dropped:
    # splitting it would make Ja'Marr Chase two tokens, both meaningless.
    assert "ja'marr" in impact._tokens("Ja'Marr Chase questionable")


def test_two_tellings_of_one_suspension_fold_into_a_single_row():
    """The failure this whole stage exists for, in its Aug 22 form: one
    outlet writes the possessive, the other calls it a ban. Different
    words, different apostrophes, one event -- and a draft board that
    shows it twice is telling the owner two players are gone."""
    espn = impact.score(
        item(
            "Falcons' Pearce suspended 8 games after arrest",
            players=[PEARCE],
            source="ESPN NFL",
            published="2026-08-15T05:00:00+00:00",
        ),
        RANKS,
    )
    cbs = impact.score(
        item(
            "Falcons Pearce banned 8 games after arrest",
            players=[PEARCE],
            source="CBS Sports NFL",
            published="2026-08-15T07:00:00+00:00",
        ),
        RANKS,
    )
    kept = impact.cluster([espn, cbs])
    assert len(kept) == 1
    assert kept[0]["source_name"] == "ESPN NFL"  # first told it
    assert kept[0]["also_from"] == ["CBS Sports NFL"]
