"""Yahoo's JSON shape is the main source of bugs in this layer, so these
fixtures mirror its real quirks: index-keyed collections and split objects."""

from app.yahoo import parse


def test_normalize_index_keyed_collection():
    node = {"0": {"a": 1}, "1": {"a": 2}, "count": 2}
    assert parse.normalize(node) == [{"a": 1}, {"a": 2}]


def test_normalize_merges_split_object():
    # Yahoo splits one object across a list of single-key dicts.
    node = [{"team_key": "nfl.l.1.t.3"}, {"name": "Sunday Gravy"}]
    assert parse.normalize(node) == {"team_key": "nfl.l.1.t.3", "name": "Sunday Gravy"}


def test_normalize_keeps_real_lists():
    # Colliding keys mean it was genuinely a list of entities, not one object.
    node = [{"pick": 1}, {"pick": 2}]
    assert parse.normalize(node) == [{"pick": 1}, {"pick": 2}]


def test_parse_draft_results_sorts_by_pick():
    payload = {
        "fantasy_content": {
            "league": {
                "draft_results": {
                    "0": {
                        "draft_result": {
                            "pick": "3",
                            "round": "1",
                            "team_key": "t3",
                            "player_key": "p3",
                        }
                    },
                    "1": {
                        "draft_result": {
                            "pick": "1",
                            "round": "1",
                            "team_key": "t1",
                            "player_key": "p1",
                        }
                    },
                    "count": 2,
                }
            }
        }
    }
    picks = parse.parse_draft_results(payload)
    assert [p["pick"] for p in picks] == ["1", "3"]
    assert picks[0]["player_key"] == "p1"


def test_parse_roster_extracts_status_and_position():
    payload = {
        "fantasy_content": {
            "team": {
                "roster": {
                    "players": {
                        "0": {
                            "player": [
                                [
                                    {"player_key": "nfl.p.100"},
                                    {"name": {"full": "Christian McCaffrey"}},
                                    {"editorial_team_abbr": "SF"},
                                    {"display_position": "RB"},
                                    {"status": "Q"},
                                    {"status_full": "Questionable"},
                                    {"bye_weeks": {"week": "9"}},
                                ],
                                {"selected_position": {"position": "RB"}},
                            ]
                        },
                        "count": 1,
                    }
                }
            }
        }
    }
    players = parse.parse_roster(payload)
    assert len(players) == 1
    player = players[0]
    assert player["name"] == "Christian McCaffrey"
    assert player["team"] == "SF"
    assert player["status"] == "Q"
    assert player["selected_position"] == "RB"
    assert player["bye_week"] == "9"
