"""Player-tagging tests. No network -- the index is built from a fixture."""

from app.feeds import players

RAW = {
    "9493": {
        "active": True,
        "position": "WR",
        "full_name": "Puka Nacua",
        "team": "LAR",
        "injury_status": "Questionable",
    },
    "1001": {
        "active": True,
        "position": "RB",
        "full_name": "Bijan Robinson",
        "team": "ATL",
        "injury_status": None,
    },
    "1002": {
        "active": True,
        "position": "WR",
        "full_name": "Amon-Ra St. Brown",
        "team": "DET",
        "injury_status": None,
    },
    "1003": {
        "active": True,
        "position": "TE",
        "full_name": "Brock Bowers",
        "team": "LV",
        "injury_status": None,
    },
    # Two active Smiths -- the surname must stay ambiguous.
    "1004": {
        "active": True,
        "position": "WR",
        "full_name": "DeVonta Smith",
        "team": "PHI",
        "injury_status": None,
    },
    "1005": {
        "active": True,
        "position": "TE",
        "full_name": "Jonnu Smith",
        "team": "PIT",
        "injury_status": None,
    },
    # Suffix in the stored name; feeds often drop it.
    "1006": {
        "active": True,
        "position": "RB",
        "full_name": "Marvin Harrison Jr.",
        "team": "ARI",
        "injury_status": None,
    },
    # Filtered out: retired, and a non-fantasy position.
    "1007": {
        "active": False,
        "position": "WR",
        "full_name": "Retired Guy",
        "team": None,
        "injury_status": None,
    },
    "1008": {
        "active": True,
        "position": "LB",
        "full_name": "Roquan Smith",
        "team": "BAL",
        "injury_status": None,
    },
    # A fantasy TE and a cornerback share a surname -- the bare form must not
    # resolve, because the index cannot see the cornerback as a taggable player.
    "1009": {
        "active": True,
        "position": "TE",
        "full_name": "Dan Arnold",
        "team": "SF",
        "injury_status": None,
    },
    "1010": {
        "active": True,
        "position": "CB",
        "full_name": "Terrion Arnold",
        "team": "SEA",
        "injury_status": None,
    },
    # Surname that is also an ordinary English word.
    "1011": {
        "active": True,
        "position": "RB",
        "full_name": "Braylon Heard",
        "team": "NYJ",
        "injury_status": None,
    },
}

INDEX = players.build_index(RAW)


def test_index_keeps_only_active_fantasy_positions():
    names = {p["name"] for p in INDEX["players"].values()}
    assert "Retired Guy" not in names  # inactive
    assert "Roquan Smith" not in names  # LB is not a fantasy position here
    assert "Puka Nacua" in names


def test_matches_a_full_name():
    found = players.find_players("Puka Nacua expected back at practice next week", INDEX)
    assert [p["name"] for p in found] == ["Puka Nacua"]
    assert found[0]["position"] == "WR"
    assert found[0]["injury_status"] == "Questionable"


def test_matches_a_unique_surname_alone():
    """Real headline shape: outlets drop first names in titles."""
    found = players.find_players("Falcons' Bowers ruled out for Sunday", INDEX)
    assert [p["name"] for p in found] == ["Brock Bowers"]


def test_refuses_to_guess_an_ambiguous_surname():
    """Two active Smiths -- naming one would be worse than naming none."""
    assert players.find_players("Smith limited in practice", INDEX) == []
    # ...but the full name still resolves
    found = players.find_players("DeVonta Smith limited in practice", INDEX)
    assert [p["name"] for p in found] == ["DeVonta Smith"]


def test_matches_across_a_missing_suffix():
    found = players.find_players("Marvin Harrison torched the secondary", INDEX)
    assert [p["name"] for p in found] == ["Marvin Harrison Jr."]


def test_handles_punctuation_and_accents_in_names():
    found = players.find_players("Amon-Ra St. Brown leads the team in targets", INDEX)
    assert [p["name"] for p in found] == ["Amon-Ra St. Brown"]


def test_finds_several_players_in_one_item_without_duplicates():
    text = "Bijan Robinson and Puka Nacua both practiced; Bijan Robinson looked fast."
    found = players.find_players(text, INDEX)
    assert [p["name"] for p in found] == ["Bijan Robinson", "Puka Nacua"]


def test_no_match_returns_empty():
    assert players.find_players("Owners approve new stadium financing", INDEX) == []


def test_does_not_match_inside_a_longer_word():
    # "Nacuas" is not "Nacua"; token matching must not do substrings.
    assert players.find_players("Nacuas everywhere", INDEX) == []


def test_tag_items_attaches_players_to_each_item():
    items = [
        {"title": "Puka Nacua expected back", "summary": ""},
        {"title": "League news", "summary": "Nothing about anyone."},
    ]
    tagged = players.tag_items(items, INDEX)
    assert [p["name"] for p in tagged[0]["players"]] == ["Puka Nacua"]
    assert tagged[1]["players"] == []


def test_summary_is_searched_not_just_the_title():
    """Headlines often omit the name: 'Nursing soft-tissue injury -- room wide open'."""
    items = [{"title": "Nursing soft-tissue injury", "summary": "With Bijan Robinson dinged..."}]
    tagged = players.tag_items(items, INDEX)
    assert [p["name"] for p in tagged[0]["players"]] == ["Bijan Robinson"]


def test_ambiguous_across_positions_is_refused():
    """Live failure: "Seahawks cite positive reviews in adding Arnold" tagged
    Dan Arnold (TE) when the story was about Terrion Arnold, a cornerback."""
    assert players.find_players("Seahawks cite positive reviews in adding Arnold", INDEX) == []
    found = players.find_players("Dan Arnold caught two touchdowns", INDEX)
    assert [p["name"] for p in found] == ["Dan Arnold"]


def test_common_word_surname_is_refused_bare():
    """Live failure: "sources heard" tagged Braylon Heard."""
    assert players.find_players("sources heard the deal was close", INDEX) == []
    assert players.find_players("Sources Heard", INDEX) == []
    found = players.find_players("Braylon Heard took first-team reps", INDEX)
    assert [p["name"] for p in found] == ["Braylon Heard"]


def test_surname_followed_by_a_capitalised_word_is_treated_as_a_first_name():
    """A capitalised surname followed by another capitalised word is almost
    always someone's first name, so the bare match is withheld."""
    assert players.find_players("Rookie TE Bowers Johnson signed today", INDEX) == []
    # Alone, with lowercase text after it, the same surname resolves.
    found = players.find_players("Bowers torched the Ravens secondary", INDEX)
    assert [p["name"] for p in found] == ["Brock Bowers"]


def test_chase_stays_refused_bare_even_though_the_surname_is_unique():
    """Live failure: "Chase Bisontis has torn MCL" tagged Ja'Marr Chase.
    "chase" is an ordinary verb, so the bare form is never worth the risk --
    the full name still resolves, which is how outlets usually write him."""
    idx = players.build_index(
        {
            **RAW,
            "2001": {
                "active": True,
                "position": "WR",
                "full_name": "Ja'Marr Chase",
                "team": "CIN",
                "injury_status": None,
            },
        }
    )
    assert players.find_players("Cards rookie OL Chase Bisontis has torn MCL", idx) == []
    assert players.find_players("Chase torched the Ravens secondary", idx) == []
    found = players.find_players("Ja'Marr Chase torched the Ravens", idx)
    assert [p["name"] for p in found] == ["Ja'Marr Chase"]


def test_lowercase_surname_does_not_match():
    found = players.find_players("the bowers of the stadium", INDEX)
    assert found == []


def test_dotted_and_initialed_names_still_enrich():
    """'C.J. Stroud' normalizes with a double space; the by_name keys are
    single-spaced. The tagger must join-split or every initialed player
    loses his rank enrichment."""
    from app.feeds import players as players_mod

    index = players_mod.build_index(
        {
            "77": {
                "active": True,
                "position": "QB",
                "full_name": "C.J. Stroud",
                "team": "HOU",
                "injury_status": None,
                "search_rank": 30,
            }
        }
    )
    seeded = {
        "title": "Texans QB C.J. Stroud sharp in practice",
        "summary": "",
        "players": [{"id": "rw:cj-stroud", "name": "C.J. Stroud", "position": "QB", "team": None}],
    }
    players_mod.tag_items([seeded], index)

    assert seeded["players"][0]["id"] == "77"
    assert seeded["players"][0]["rank"] == 30
