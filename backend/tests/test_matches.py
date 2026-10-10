"""Matches and their relationships to teams and players (acceptance test B)."""
import pytest

from tests.helpers import add_to_lineup, create_match, create_player


def test_a_match_creates_its_teams_competition_and_season(client):
    match = create_match(client, competition="Example League", season="2025/26", venue="Northside Park",
                         home_score=2, away_score=1, home_formation="4-3-3", away_formation="4-4-2")
    assert match["title"] == "Northside FC v Riverton United"
    assert match["home_team"]["name"] == "Northside FC"
    assert match["competition"]["name"] == "Example League"
    assert match["season"]["name"] == "2025/26"
    assert (match["home_score"], match["away_score"]) == (2, 1)
    assert {team["name"] for team in client.get("/api/teams").json()} == {"Northside FC", "Riverton United"}


def test_an_unknown_result_is_not_a_nil_nil_draw(client):
    match = create_match(client)
    assert match["home_score"] is None and match["away_score"] is None


@pytest.mark.parametrize("bad", [
    {"home_team": "Northside FC", "away_team": "northside fc"},  # a team cannot play itself
    {"home_team": "A", "away_team": "B", "home_score": 2},  # one score without the other
    {"home_team": "A", "away_team": "B", "home_score": -1, "away_score": 0},
    {"home_team": "A", "away_team": "B", "match_date": "1700-01-01"},
    {"home_team": "", "away_team": "B"},
])
def test_invalid_match_data_is_rejected(client, bad):
    assert client.post("/api/matches", json=bad).status_code == 422
    assert client.get("/api/matches").json() == []


def test_the_same_match_cannot_be_recorded_twice(client):
    first = create_match(client)
    duplicate = client.post("/api/matches", json={"home_team": "northside fc", "away_team": "Riverton United",
                                                  "match_date": "2026-03-08"})
    assert duplicate.status_code == 409
    assert duplicate.json()["existing_match_id"] == first["id"]
    create_match(client, match_date="2026-04-12")  # the return fixture on another day is fine
    create_match(client, home_team="Riverton United", away_team="Northside FC")  # so is the reverse fixture


def test_several_players_are_linked_to_one_match(client):
    """Acceptance test B: create a match, associate multiple players, verify the relationships."""
    match = create_match(client)
    striker = create_player(client, full_name="Sam Finisher", primary_position="ST")
    winger = create_player(client, full_name="Lee Wide", primary_position="RW")
    defender = create_player(client, full_name="Pat Stopper", primary_position="CB")

    add_to_lineup(client, match["id"], striker["id"], side="home", shirt_number=9, position="ST", minute_off=70)
    add_to_lineup(client, match["id"], winger["id"], side="home", is_starter=False, minute_on=70, shirt_number=17)
    add_to_lineup(client, match["id"], defender["id"], side="away", shirt_number=4)

    detail = client.get(f"/api/matches/{match['id']}").json()
    lineup = [(a["player"]["full_name"], a["side"], a["team"]["name"], a["is_starter"]) for a in detail["appearances"]]
    assert lineup == [
        ("Sam Finisher", "home", "Northside FC", True),
        ("Lee Wide", "home", "Northside FC", False),
        ("Pat Stopper", "away", "Riverton United", True),
    ]
    substitution = {a["player"]["full_name"]: (a["minute_on"], a["minute_off"]) for a in detail["appearances"]}
    assert substitution["Sam Finisher"] == (None, 70)
    assert substitution["Lee Wide"] == (70, None)

    # The same relationship seen from the player's side.
    timeline = client.get(f"/api/players/{striker['id']}/timeline").json()
    assert [(e["kind"], e["title"], e["match_id"]) for e in timeline] == [
        ("appearance", "Played in Northside FC v Riverton United", match["id"])]
    assert client.get(f"/api/players/{striker['id']}").json()["counts"]["appearances"] == 1


def test_lineup_rules(client):
    match = create_match(client)
    player = create_player(client)
    add_to_lineup(client, match["id"], player["id"])

    def post(payload):
        return client.post(f"/api/matches/{match['id']}/appearances", json=payload)

    assert post({"player_id": player["id"], "side": "away"}).status_code == 409  # already in the lineup
    assert post({"player_id": 999, "side": "home"}).status_code == 404  # no such player
    other = create_player(client, full_name="Other Player")
    assert post({"player_id": other["id"], "side": "home", "minute_on": 60}).status_code == 422  # a starter came on?
    assert post({"player_id": other["id"], "side": "home", "is_starter": False,
                 "minute_on": 60, "minute_off": 50}).status_code == 422  # off before on
    assert post({"player_id": other["id"], "side": "middle"}).status_code == 422


def test_editing_and_removing_a_lineup_entry(client):
    match = create_match(client)
    player = create_player(client)
    entry = add_to_lineup(client, match["id"], player["id"], side="home")

    updated = client.put(f"/api/appearances/{entry['id']}",
                         json={"player_id": player["id"], "side": "away", "position": "CB", "minute_off": 88})
    assert updated.status_code == 200
    assert (updated.json()["side"], updated.json()["team"]["name"]) == ("away", "Riverton United")

    assert client.delete(f"/api/appearances/{entry['id']}").status_code == 204
    assert client.get(f"/api/matches/{match['id']}").json()["appearances"] == []


def test_lineups_follow_their_side_when_a_team_is_corrected(client):
    match = create_match(client)
    player = create_player(client)
    add_to_lineup(client, match["id"], player["id"], side="home")

    client.put(f"/api/matches/{match['id']}", json={"home_team": "Northside Athletic",
                                                    "away_team": "Riverton United", "match_date": "2026-03-08"})
    entry = client.get(f"/api/matches/{match['id']}").json()["appearances"][0]
    assert (entry["side"], entry["team"]["name"]) == ("home", "Northside Athletic")


def test_match_filters(client):
    older = create_match(client, match_date="2025-11-02", competition="Example League")
    newer = create_match(client, home_team="Riverton United", away_team="Harbour City", match_date="2026-03-08",
                         competition="Example Cup", venue="Riverside Ground")
    undated = create_match(client, home_team="Harbour City", away_team="Northside FC", match_date=None)

    def ids(**params):
        return [match["id"] for match in client.get("/api/matches", params=params).json()]

    assert ids() == [newer["id"], older["id"], undated["id"]]  # newest first, unknown dates last
    assert ids(date_from="2026-01-01") == [newer["id"]]
    assert ids(date_to="2025-12-31") == [older["id"]]
    assert ids(competition_id=newer["competition"]["id"]) == [newer["id"]]
    assert ids(team_id=older["home_team"]["id"]) == [older["id"], undated["id"]]
    assert ids(q="harbour") == [newer["id"], undated["id"]]
    assert ids(q="riverside") == [newer["id"]]


def test_a_match_with_records_is_only_deleted_after_confirmation(client):
    match = create_match(client)
    player = create_player(client)
    add_to_lineup(client, match["id"], player["id"])

    refused = client.delete(f"/api/matches/{match['id']}")
    assert refused.status_code == 409
    assert refused.json()["dependencies"] == {"observations": 0, "statistics": 0, "appearances": 1, "videos": 0}

    assert client.delete(f"/api/matches/{match['id']}", params={"cascade": True}).status_code == 204
    assert client.get(f"/api/matches/{match['id']}").status_code == 404
    assert client.get(f"/api/players/{player['id']}").status_code == 200  # the player is not part of the match


def test_teams_in_use_cannot_be_deleted(client):
    match = create_match(client)
    team_id = match["home_team"]["id"]
    refused = client.delete(f"/api/teams/{team_id}")
    assert refused.status_code == 409
    assert refused.json()["in_use"] == {"matches": 1}

    client.delete(f"/api/matches/{match['id']}")
    assert client.delete(f"/api/teams/{team_id}").status_code == 204


def test_renaming_a_team_updates_it_everywhere(client):
    match = create_match(client)
    team_id = match["home_team"]["id"]
    assert client.put(f"/api/teams/{team_id}", json={"name": "Northside Athletic"}).status_code == 200
    assert client.get(f"/api/matches/{match['id']}").json()["title"] == "Northside Athletic v Riverton United"
    # A name that another team already has is refused.
    assert client.put(f"/api/teams/{team_id}", json={"name": "riverton united"}).status_code == 409
