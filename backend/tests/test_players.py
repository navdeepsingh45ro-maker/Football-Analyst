"""Players: creating, validating, finding, and deleting deliberately."""
import pytest

from tests.helpers import create_assessment, create_player


def test_a_player_needs_only_a_name(client):
    player = create_player(client, full_name="Jordan Sample")
    assert player["full_name"] == "Jordan Sample"
    # Everything not supplied is unknown (None), never a made-up default.
    for field in ("date_of_birth", "age", "nationality", "height_cm", "preferred_foot", "primary_position",
                  "current_team", "national_team", "shirt_number", "photo_url", "notes"):
        assert player[field] is None, field
    assert player["secondary_positions"] == []
    assert player["created_at"].endswith("Z")


def test_blank_form_fields_are_stored_as_unknown(client):
    player = create_player(client, date_of_birth="", height_cm="", nationality="   ", preferred_foot="",
                           shirt_number="", current_team="")
    assert player["date_of_birth"] is None
    assert player["height_cm"] is None  # unknown, not 0
    assert player["nationality"] is None
    assert player["preferred_foot"] is None
    assert player["shirt_number"] is None
    assert player["current_team"] is None


def test_explicit_nulls_are_accepted_as_unknown(client):
    # The frontend sends null (not "") for empty fields; every optional field must accept it.
    player = create_player(client, date_of_birth=None, height_cm=None, nationality=None, preferred_foot=None,
                           shirt_number=None, current_team=None, photo_url=None, primary_position=None)
    assert player["height_cm"] is None and player["nationality"] is None


def test_full_profile_round_trip(client):
    created = create_player(
        client, full_name="Casey Placeholder", date_of_birth="2000-02-29", nationality="Exampleland",
        height_cm=181, preferred_foot="left", primary_position="st", secondary_positions=["lw", "ST", "LW", " "],
        current_team="Northside FC", national_team="Exampleland", shirt_number=9,
        photo_url="https://example.com/casey.jpg", notes="Fictional test player.",
    )
    fetched = client.get(f"/api/players/{created['id']}").json()
    assert fetched["date_of_birth"] == "2000-02-29"
    assert isinstance(fetched["age"], int)
    assert fetched["primary_position"] == "ST"  # spelled like the suggestion list
    assert fetched["secondary_positions"] == ["LW"]  # tidied: no repeats, no blanks, not the primary
    assert fetched["current_team"]["name"] == "Northside FC"
    assert fetched["national_team"]["name"] == "Exampleland"
    assert fetched["counts"] == {"observations": 0, "assessments": 0, "appearances": 0, "statistics": 0,
                                 "diagrams": 0, "notes": 0}


def test_a_team_is_created_once_and_reused(client):
    first = create_player(client, full_name="Player One", current_team="Northside FC")
    second = create_player(client, full_name="Player Two", current_team="northside fc")  # different case
    assert first["current_team"]["id"] == second["current_team"]["id"]
    assert [team["name"] for team in client.get("/api/teams").json()] == ["Northside FC"]


def test_search_and_filters(client):
    striker = create_player(client, full_name="Sam Finisher", primary_position="ST", current_team="Northside FC")
    create_player(client, full_name="Robin Keeper", primary_position="GK", nationality="Exampleland")

    assert [p["full_name"] for p in client.get("/api/players").json()] == ["Robin Keeper", "Sam Finisher"]
    assert [p["full_name"] for p in client.get("/api/players", params={"q": "fin"}).json()] == ["Sam Finisher"]
    assert [p["full_name"] for p in client.get("/api/players", params={"q": "exampleland"}).json()] == ["Robin Keeper"]
    assert [p["full_name"] for p in client.get("/api/players", params={"position": "GK"}).json()] == ["Robin Keeper"]
    team_id = striker["current_team"]["id"]
    assert [p["full_name"] for p in client.get("/api/players", params={"team_id": team_id}).json()] == ["Sam Finisher"]
    # % and _ are searched for literally, not treated as wildcards.
    assert client.get("/api/players", params={"q": "%"}).json() == []


def test_same_name_and_birth_date_is_a_duplicate(client):
    original = create_player(client, full_name="Alex Example", date_of_birth="1999-05-05")
    response = client.post("/api/players", json={"full_name": "alex example", "date_of_birth": "1999-05-05"})
    assert response.status_code == 409
    assert response.json()["existing_player_id"] == original["id"]
    assert response.json()["can_override"] is False
    # Confirming does not help here: it is certainly the same person.
    again = client.post("/api/players", params={"allow_duplicate": True},
                        json={"full_name": "Alex Example", "date_of_birth": "1999-05-05"})
    assert again.status_code == 409


def test_same_name_without_birth_dates_asks_before_creating(client):
    create_player(client, full_name="Alex Example")
    response = client.post("/api/players", json={"full_name": "Alex Example"})
    assert response.status_code == 409
    assert response.json()["can_override"] is True
    confirmed = client.post("/api/players", params={"allow_duplicate": True}, json={"full_name": "Alex Example"})
    assert confirmed.status_code == 201
    assert len(client.get("/api/players").json()) == 2


def test_same_name_with_different_birth_dates_is_fine(client):
    create_player(client, full_name="Alex Example", date_of_birth="1999-05-05")
    create_player(client, full_name="Alex Example", date_of_birth="2003-01-01")


@pytest.mark.parametrize("bad", [
    {"full_name": "   "},
    {"full_name": "X", "height_cm": 20},
    {"full_name": "X", "height_cm": "tall"},
    {"full_name": "X", "date_of_birth": "2999-01-01"},
    {"full_name": "X", "date_of_birth": "not-a-date"},
    {"full_name": "X", "preferred_foot": "middle"},
    {"full_name": "X", "shirt_number": 0},
    {"full_name": "X", "photo_url": "javascript:alert(1)"},
    {"full_name": "X", "nationality": "N" * 81},  # longer than the column allows
    {"full_name": "X", "favourite_colour": "green"},  # a field that does not exist
])
def test_invalid_player_data_is_rejected_and_nothing_is_saved(client, bad):
    response = client.post("/api/players", json=bad)
    assert response.status_code == 422, response.text
    assert client.get("/api/players").json() == []


def test_missing_player_is_404(client):
    assert client.get("/api/players/999").status_code == 404
    assert client.put("/api/players/999", json={"full_name": "Nobody"}).status_code == 404
    assert client.delete("/api/players/999").status_code == 404


def test_editing_replaces_the_biography(client):
    player = create_player(client, full_name="Alex Example", current_team="Northside FC", shirt_number=9)
    response = client.put(f"/api/players/{player['id']}",
                          json={"full_name": "Alex Example", "current_team": "Riverton United", "height_cm": 180})
    assert response.status_code == 200
    updated = response.json()
    assert updated["current_team"]["name"] == "Riverton United"
    assert updated["height_cm"] == 180
    assert updated["shirt_number"] is None  # the form sent no number, so it is unknown now


def test_a_player_with_nothing_attached_is_deleted_directly(client):
    player = create_player(client)
    assert client.delete(f"/api/players/{player['id']}").status_code == 204
    assert client.get(f"/api/players/{player['id']}").status_code == 404


def test_a_player_with_records_is_only_deleted_after_confirmation(client):
    player = create_player(client)
    create_assessment(client, player["id"])

    refused = client.delete(f"/api/players/{player['id']}")
    assert refused.status_code == 409
    assert refused.json()["dependencies"]["assessments"] == 1
    assert client.get(f"/api/players/{player['id']}").status_code == 200  # still there

    assert client.get(f"/api/players/{player['id']}/dependencies").json()["assessments"] == 1
    assert client.delete(f"/api/players/{player['id']}", params={"cascade": True}).status_code == 204
    assert client.get(f"/api/players/{player['id']}").status_code == 404
