"""The coaching notebook: notes and training ideas stay traceable to what was observed."""
import pytest

from tests.helpers import create_match, create_observation, create_player


@pytest.fixture
def observed(client):
    player = create_player(client, full_name="Sam Finisher", primary_position="ST")
    match = create_match(client)
    observation = create_observation(
        client, [player["id"]], match_id=match["id"], video_time_seconds=612.5, movement_category="Diagonal run",
        notes="Moves away from the centre-back before attacking the space behind him.")
    return {"player": player, "match": match, "observation": observation}


def _note(client, **overrides) -> dict:
    body = {"note_type": "Coaching principle", "title": "Create separation before the run", **overrides}
    response = client.post("/api/notes", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_an_observation_becomes_a_note_and_then_a_training_idea(client, observed):
    """observation -> coaching note -> training idea, with every link kept."""
    observation_id = observed["observation"]["id"]
    note = _note(client, body="Practise creating separation before accelerating into the space behind a defender.",
                 player_id=observed["player"]["id"], match_id=observed["match"]["id"],
                 observation_ids=[observation_id], tags=["striker movement", "Striker Movement", "  "])
    assert note["tags"] == ["striker movement"]  # tidied: no repeats, no blanks
    assert note["player"]["full_name"] == "Sam Finisher"
    assert [(o["id"], o["movement_category"], o["video_time_seconds"]) for o in note["observations"]] == [
        (observation_id, "Diagonal run", 612.5)]

    idea = client.post("/api/training-ideas", json={
        "title": "Check away, then go", "objective": "Timing the double movement against a centre-back.",
        "setup": "20 x 30 m channel, one server, one striker, one passive then active defender.",
        "coaching_points": "First step away must be sharp enough to move the defender.",
        "duration_minutes": 15, "players_needed": "3 + server",
        "source_note_id": note["id"], "observation_ids": [observation_id]})
    assert idea.status_code == 201, idea.text
    idea = idea.json()
    assert idea["source_note"] == {"id": note["id"], "title": "Create separation before the run"}
    assert [o["id"] for o in idea["observations"]] == [observation_id]

    # The trail can be followed from every end.
    derived = client.get(f"/api/observations/{observation_id}").json()["derived"]
    assert {(item["kind"], item["title"]) for item in derived} == {
        ("coaching_note", "Create separation before the run"), ("training_idea", "Check away, then go")}
    assert client.get(f"/api/notes/{note['id']}").json()["training_ideas"] == [{"id": idea["id"], "title": "Check away, then go"}]
    assert [n["id"] for n in client.get("/api/notes", params={"observation_id": observation_id}).json()] == [note["id"]]
    assert [i["id"] for i in client.get("/api/training-ideas", params={"observation_id": observation_id}).json()] == [idea["id"]]
    # And the note shows up in the player's development timeline.
    timeline = client.get(f"/api/players/{observed['player']['id']}/timeline").json()
    assert ("note", "Create separation before the run") in [(event["kind"], event["title"]) for event in timeline]


def test_deleting_one_end_of_the_trail_keeps_the_rest(client, observed):
    observation_id = observed["observation"]["id"]
    note = _note(client, observation_ids=[observation_id])
    idea = client.post("/api/training-ideas", json={"title": "Check away, then go", "source_note_id": note["id"],
                                                    "observation_ids": [observation_id]}).json()

    # Deleting the observation removes only the link; what you wrote stays.
    assert client.delete(f"/api/observations/{observation_id}").status_code == 204
    assert client.get(f"/api/notes/{note['id']}").json()["observations"] == []
    assert client.get(f"/api/training-ideas/{idea['id']}").json()["observations"] == []

    # Deleting the note keeps the training idea that grew out of it.
    assert client.delete(f"/api/notes/{note['id']}").status_code == 204
    kept = client.get(f"/api/training-ideas/{idea['id']}").json()
    assert kept["title"] == "Check away, then go" and kept["source_note"] is None
    assert client.delete(f"/api/training-ideas/{idea['id']}").status_code == 204
    assert client.get("/api/training-ideas").json() == []


def test_open_questions_are_listed_as_outstanding_until_done(client, observed):
    question = _note(client, note_type="question for future analysis", status="open",
                     title="Does he make the same run against a back three?")
    assert question["note_type"] == "Question for future analysis"  # matched to the suggestion's spelling
    _note(client, note_type="Tactical concept", title="Half-space occupation")  # not a task

    waiting = client.get("/api/dashboard").json()["outstanding"]["open_notes"]
    assert [entry["title"] for entry in waiting] == ["Does he make the same run against a back three?"]
    assert [n["id"] for n in client.get("/api/notes", params={"status": "open"}).json()] == [question["id"]]

    done = client.put(f"/api/notes/{question['id']}", json={
        "note_type": question["note_type"], "title": question["title"], "status": "done"})
    assert done.status_code == 200 and done.json()["status"] == "done"
    assert client.get("/api/dashboard").json()["outstanding"]["open_notes"] == []


def test_notes_can_be_searched_and_edited_in_place(client, observed):
    first = _note(client, title="Pressing triggers", body="Back pass to the goalkeeper.")
    second = _note(client, note_type="My own category", title="Rest defence", body="Two plus one behind the ball.")
    assert second["note_type"] == "My own category"  # your own wording is kept

    assert [n["id"] for n in client.get("/api/notes", params={"q": "goalkeeper"}).json()] == [first["id"]]
    assert [n["id"] for n in client.get("/api/notes", params={"note_type": "My own category"}).json()] == [second["id"]]
    assert client.get("/api/notes", params={"q": "100%"}).json() == []

    edited = client.put(f"/api/notes/{first['id']}", json={"note_type": "Coaching principle", "title": "Pressing triggers",
                                                          "body": "A slow back pass, or a poor first touch."})
    assert edited.json()["id"] == first["id"]
    assert len(client.get("/api/notes").json()) == 2


@pytest.mark.parametrize("path, body, expected", [
    ("/api/notes", {"note_type": "Tactical concept"}, 422),  # no title
    ("/api/notes", {"note_type": "", "title": "x"}, 422),
    ("/api/notes", {"note_type": "t", "title": "x", "status": "maybe"}, 422),
    ("/api/notes", {"note_type": "t", "title": "x", "observation_ids": [999]}, 404),
    ("/api/notes", {"note_type": "t", "title": "x", "observation_ids": [1, 1]}, 422),
    ("/api/notes", {"note_type": "t", "title": "x", "player_id": 999}, 404),
    ("/api/training-ideas", {"objective": "no title"}, 422),
    ("/api/training-ideas", {"title": "x", "duration_minutes": 0}, 422),
    ("/api/training-ideas", {"title": "x", "source_note_id": 999}, 404),
])
def test_invalid_notebook_entries_are_rejected(client, observed, path, body, expected):
    assert client.post(path, json=body).status_code == expected, body
    assert client.get("/api/notes").json() == [] and client.get("/api/training-ideas").json() == []


def test_blank_optional_fields_are_unknown(client):
    idea = client.post("/api/training-ideas", json={"title": "Rondo", "duration_minutes": "", "objective": "  "})
    assert idea.status_code == 201, idea.text
    assert idea.json()["duration_minutes"] is None and idea.json()["objective"] is None
    assert client.get("/api/notes/999").status_code == 404
    assert client.delete("/api/training-ideas/999").status_code == 404
