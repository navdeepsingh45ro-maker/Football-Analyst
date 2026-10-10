"""Observations: acceptance tests C (independent records), D (retrieval from the profile),
H (history survives biography changes), I (filters) and parts of K (failing safely)."""
import pytest

from tests.helpers import add_to_lineup, create_match, create_observation, create_player, sample_diagram


@pytest.fixture
def scene(client):
    """One match with a video link, and a striker who played in it."""
    match = create_match(client, competition="Example League", season="2025/26")
    striker = create_player(client, full_name="Sam Finisher", primary_position="ST", current_team="Northside FC")
    add_to_lineup(client, match["id"], striker["id"], side="home")
    video = client.post(f"/api/matches/{match['id']}/videos",
                        json={"location": "https://example.com/full-match.mp4"}).json()
    return {"match": match, "striker": striker, "video": video}


def _ids(client, **params) -> list[int]:
    response = client.get("/api/observations", params=params)
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


# ── C: several observations for the same player in the same match ────────────
def test_several_observations_for_one_player_in_one_match_are_saved_independently(client, scene):
    match_id, striker_id, video_id = scene["match"]["id"], scene["striker"]["id"], scene["video"]["id"]
    common = {"match_id": match_id, "video_reference_id": video_id}

    first = create_observation(client, [striker_id], **common, video_time_seconds=612.5,
                               movement_category="Diagonal run", notes="Starts on the blind side of the CB.")
    second = create_observation(client, [striker_id], **common, video_time_seconds=1934,
                                movement_category="Checking towards the ball", notes="Drops to link play.")
    third = create_observation(client, [striker_id], **common, video_time_seconds=4020, category="Finishing",
                               outcome="Goal", notes="First-time finish across the keeper.")

    assert len({first["id"], second["id"], third["id"]}) == 3  # three separate records
    assert _ids(client, player_id=striker_id, match_id=match_id) == [first["id"], second["id"], third["id"]]

    # Changing one leaves the others exactly as they were.
    client.put(f"/api/observations/{second['id']}", json={
        "player_ids": [striker_id], **common, "video_time_seconds": 1934, "category": "Off-ball movement",
        "movement_category": "Dropping between the lines", "notes": "Edited note."})
    assert client.get(f"/api/observations/{first['id']}").json()["notes"] == "Starts on the blind side of the CB."
    assert client.get(f"/api/observations/{third['id']}").json()["outcome"] == "Goal"

    # Deleting one leaves the others.
    assert client.delete(f"/api/observations/{first['id']}").status_code == 204
    assert _ids(client, player_id=striker_id) == [second["id"], third["id"]]


# ── D: retrieval from the player's profile ───────────────────────────────────
def test_a_players_observations_come_back_with_timestamps_and_notes(client, scene):
    match_id, striker_id = scene["match"]["id"], scene["striker"]["id"]
    create_observation(client, [striker_id], match_id=match_id, video_time_seconds="35:10",
                       match_clock_seconds="32:14", notes="Second run.", confidence="high")
    create_observation(client, [striker_id], match_id=match_id, video_time_seconds="10:12.5", notes="First run.")

    page = client.get("/api/observations", params={"player_id": striker_id}).json()
    assert page["total"] == 2
    # In the order things happened in the video, not the order they were typed in.
    assert [(o["video_time_seconds"], o["notes"]) for o in page["items"]] == [(612.5, "First run."),
                                                                              (2110.0, "Second run.")]
    later = page["items"][1]
    assert later["match_clock_seconds"] == 1934  # 32:14 on the scoreboard
    assert later["match"] == {"id": match_id, "title": "Northside FC v Riverton United", "match_date": "2026-03-08"}
    assert later["players"] == [{"id": striker_id, "full_name": "Sam Finisher", "primary_position": "ST",
                                 "role": "primary"}]
    assert later["confidence"] == "high"

    profile = client.get(f"/api/players/{striker_id}").json()
    assert profile["counts"]["observations"] == 2
    timeline = client.get(f"/api/players/{striker_id}/timeline").json()
    assert [event["kind"] for event in timeline] == ["observation", "observation", "appearance"]
    assert timeline[0]["date"] == "2026-03-08"  # the date it HAPPENED: the match date


def test_the_three_kinds_of_time_are_never_mixed_up(client, scene):
    observation = create_observation(client, [scene["striker"]["id"]], match_id=scene["match"]["id"],
                                     video_time_seconds="1:02:03", match_clock_seconds="58:40")
    assert observation["video_time_seconds"] == 3723.0  # position in the video file
    assert observation["match_clock_seconds"] == 3520  # the scoreboard clock
    assert observation["created_at"].endswith("Z")  # a calendar moment, in UTC
    assert observation["created_at"][:4].isdigit()


@pytest.mark.parametrize("bad_time", ["ab:cd", "12:75", "1:2:3:4", "-5", "-1:00"])
def test_a_malformed_time_is_rejected(client, scene, bad_time):
    response = client.post("/api/observations", json={
        "player_ids": [scene["striker"]["id"]], "category": "Positioning", "video_time_seconds": bad_time})
    assert response.status_code == 422


# ── Editing in place ─────────────────────────────────────────────────────────
def test_editing_keeps_the_same_identifier_and_makes_no_copy(client, scene):
    striker_id = scene["striker"]["id"]
    observation = create_observation(client, [striker_id], notes="Original.")
    for wording in ("Second thoughts.", "Final wording."):
        response = client.put(f"/api/observations/{observation['id']}",
                              json={"player_ids": [striker_id], "category": "Off-ball movement", "notes": wording})
        assert response.status_code == 200
        assert response.json()["id"] == observation["id"]
    page = client.get("/api/observations").json()
    assert page["total"] == 1
    assert page["items"][0]["notes"] == "Final wording."


def test_the_timestamp_only_changes_when_the_edit_says_so(client, scene):
    striker_id, match_id = scene["striker"]["id"], scene["match"]["id"]
    observation = create_observation(client, [striker_id], match_id=match_id, video_time_seconds=612.5,
                                     match_clock_seconds=540)
    body = {"player_ids": [striker_id], "match_id": match_id, "category": "Off-ball movement",
            "video_time_seconds": 612.5, "match_clock_seconds": 540, "notes": "Only the note changed."}

    edited = client.put(f"/api/observations/{observation['id']}", json=body).json()
    assert (edited["video_time_seconds"], edited["match_clock_seconds"]) == (612.5, 540)

    moved = client.put(f"/api/observations/{observation['id']}", json={**body, "video_time_seconds": 700}).json()
    assert moved["video_time_seconds"] == 700.0  # changed, because the edit explicitly asked for it


# ── Players and attachment ───────────────────────────────────────────────────
def test_several_players_can_share_one_situation(client, scene):
    striker_id = scene["striker"]["id"]
    winger = create_player(client, full_name="Lee Wide", primary_position="RW")
    observation = create_observation(client, [striker_id, winger["id"]], primary_player_id=winger["id"],
                                     movement_category="Rotation with a teammate")
    assert [(p["full_name"], p["role"]) for p in observation["players"]] == [("Lee Wide", "primary"),
                                                                            ("Sam Finisher", "involved")]
    assert _ids(client, player_id=striker_id) == [observation["id"]]
    assert _ids(client, player_id=winger["id"]) == [observation["id"]]


def test_an_observation_must_be_attached_to_a_player_or_a_match(client, scene):
    assert client.post("/api/observations", json={"category": "Pressing"}).status_code == 422
    team_level = client.post("/api/observations", json={"category": "Pressing", "match_id": scene["match"]["id"]})
    assert team_level.status_code == 201
    assert team_level.json()["players"] == []


def test_categories_are_tidied_and_your_own_wording_is_kept(client, scene):
    observation = create_observation(client, [scene["striker"]["id"]], category="  off-ball   MOVEMENT ",
                                     movement_category="diagonal run", outcome="Blocked by the keeper")
    assert observation["category"] == "Off-ball movement"  # matched a suggestion
    assert observation["movement_category"] == "Diagonal run"
    assert observation["outcome"] == "Blocked by the keeper"  # custom: kept exactly


def test_invalid_observations_are_rejected_and_nothing_is_saved(client, scene):
    striker_id, match_id = scene["striker"]["id"], scene["match"]["id"]
    other_match = create_match(client, match_date="2026-04-12")
    cases = [
        ({"player_ids": [striker_id]}, 422),  # no category
        ({"player_ids": [striker_id], "category": "   "}, 422),
        ({"player_ids": [999], "category": "Pressing"}, 404),  # no such player
        ({"player_ids": [striker_id], "category": "Pressing", "match_id": 999}, 404),
        ({"player_ids": [striker_id, striker_id], "category": "Pressing"}, 422),  # listed twice
        ({"player_ids": [striker_id], "primary_player_id": 999, "category": "Pressing"}, 422),
        ({"player_ids": [striker_id], "category": "Pressing", "confidence": "certain"}, 422),
        ({"player_ids": [striker_id], "category": "Pressing", "video_reference_id": scene["video"]["id"]}, 422),
        ({"player_ids": [striker_id], "category": "Pressing", "match_id": other_match["id"],
          "video_reference_id": scene["video"]["id"]}, 422),  # that video belongs to a different match
        ({"player_ids": [striker_id], "category": "Pressing", "mood": "happy"}, 422),  # unknown field
    ]
    for body, expected_status in cases:
        assert client.post("/api/observations", json=body).status_code == expected_status, body
    assert client.get("/api/observations").json() == {"total": 0, "items": []}
    assert client.get("/api/observations/999").status_code == 404
    assert client.put("/api/observations/999", json={"player_ids": [striker_id], "category": "x"}).status_code == 404
    assert client.delete("/api/observations/999").status_code == 404
    assert client.get("/api/observations", params={"player_id": "abc"}).status_code == 422


# ── I: filters ───────────────────────────────────────────────────────────────
def test_every_filter_returns_exactly_the_matching_observations(client):
    league = create_match(client, home_team="Northside FC", away_team="Riverton United",
                          match_date="2025-11-02", competition="Example League", season="2025/26")
    cup = create_match(client, home_team="Harbour City", away_team="Northside FC",
                       match_date="2026-03-08", competition="Example Cup", season="2025/26")
    striker = create_player(client, full_name="Sam Finisher", primary_position="ST")
    centre_back = create_player(client, full_name="Pat Stopper", primary_position="CB")

    a = create_observation(client, [striker["id"]], match_id=league["id"], video_time_seconds=300,
                           movement_category="Diagonal run", outcome="Shot", defensive_shape="4-4-2 mid block",
                           notes="Attacks the gap between centre-back and full-back.", confidence="high")
    b = create_observation(client, [striker["id"]], match_id=league["id"], video_time_seconds=900,
                           movement_category="Diagonal run", outcome="Not found by the pass")
    c = create_observation(client, [striker["id"]], match_id=cup["id"], video_time_seconds=120,
                           movement_category="Channel run", outcome="Goal", snapshot=sample_diagram(),
                           intended_space="Outside the left centre-back")
    d = create_observation(client, [centre_back["id"]], match_id=cup["id"], video_time_seconds=400,
                           category="Defensive positioning", outcome="Won the ball")
    e = create_observation(client, [striker["id"]], category="Finishing", notes="General note, no match.")

    # Newest match first; inside a match, in video order; observations with no match last.
    assert _ids(client) == [c["id"], d["id"], a["id"], b["id"], e["id"]]

    assert _ids(client, player_id=striker["id"]) == [c["id"], a["id"], b["id"], e["id"]]
    assert _ids(client, match_id=league["id"]) == [a["id"], b["id"]]
    assert _ids(client, team_id=cup["home_team"]["id"]) == [c["id"], d["id"]]  # Harbour City played once
    assert _ids(client, competition_id=cup["competition"]["id"]) == [c["id"], d["id"]]
    assert _ids(client, season_id=league["season"]["id"]) == [c["id"], d["id"], a["id"], b["id"]]
    assert _ids(client, position="CB") == [d["id"]]
    assert _ids(client, category="defensive positioning") == [d["id"]]  # case does not matter
    assert _ids(client, movement_category="Diagonal run") == [a["id"], b["id"]]
    assert _ids(client, outcome="Goal") == [c["id"]]
    assert _ids(client, ended_in_shot_or_chance=True) == [c["id"], a["id"]]
    assert _ids(client, ended_in_shot_or_chance=False) == [d["id"], b["id"], e["id"]]
    assert _ids(client, defensive_shape="4-4-2 mid block") == [a["id"]]
    assert _ids(client, confidence="high") == [a["id"]]
    assert _ids(client, date_from="2026-01-01") == [c["id"], d["id"]]
    assert _ids(client, date_to="2025-12-31") == [a["id"], b["id"]]
    assert _ids(client, has_diagram=True) == [c["id"]]
    assert _ids(client, has_diagram=False) == [d["id"], a["id"], b["id"], e["id"]]

    # Search looks in the written text and in player names; % is not a wildcard.
    assert _ids(client, q="centre-back") == [c["id"], a["id"]]
    assert _ids(client, q="stopper") == [d["id"]]
    assert _ids(client, q="100%") == []

    # Filters combine with AND.
    assert _ids(client, player_id=striker["id"], movement_category="Diagonal run", outcome="Shot") == [a["id"]]
    assert _ids(client, player_id=centre_back["id"], movement_category="Diagonal run") == []

    # Paging reports the full total.
    page = client.get("/api/observations", params={"limit": 2, "offset": 2}).json()
    assert page["total"] == 5
    assert [item["id"] for item in page["items"]] == [a["id"], b["id"]]


# ── H: history survives changes to the player ────────────────────────────────
def test_changing_the_biography_keeps_every_observation(client, scene):
    striker_id, match_id = scene["striker"]["id"], scene["match"]["id"]
    observation = create_observation(client, [striker_id], match_id=match_id, video_time_seconds=612.5,
                                     notes="Starts on the blind side.", snapshot=sample_diagram())

    client.put(f"/api/players/{striker_id}", json={"full_name": "Samuel Finisher", "primary_position": "CF",
                                                   "current_team": "Harbour City", "shirt_number": 19})

    after = client.get(f"/api/observations/{observation['id']}").json()
    assert after["id"] == observation["id"]
    assert (after["video_time_seconds"], after["notes"]) == (612.5, "Starts on the blind side.")
    assert after["match"]["id"] == match_id
    assert len(after["snapshots"][0]["annotations"]) == len(observation["snapshots"][0]["annotations"])
    assert after["players"][0]["full_name"] == "Samuel Finisher"  # shows the current name
    assert _ids(client, player_id=striker_id) == [observation["id"]]


# ── Deliberate deletion ──────────────────────────────────────────────────────
def test_deleting_a_player_removes_only_their_own_observations(client, scene):
    striker_id = scene["striker"]["id"]
    winger = create_player(client, full_name="Lee Wide")
    solo = create_observation(client, [striker_id], notes="About the striker alone.")
    shared = create_observation(client, [winger["id"], striker_id], notes="A rotation between the two.")

    refused = client.delete(f"/api/players/{striker_id}")
    assert refused.status_code == 409
    dependencies = refused.json()["dependencies"]
    assert (dependencies["observations"], dependencies["observations_deleted"],
            dependencies["observations_kept"]) == (2, 1, 1)

    assert client.delete(f"/api/players/{striker_id}", params={"cascade": True}).status_code == 204
    assert client.get(f"/api/observations/{solo['id']}").status_code == 404
    kept = client.get(f"/api/observations/{shared['id']}").json()
    assert [player["full_name"] for player in kept["players"]] == ["Lee Wide"]


def test_a_match_with_observations_is_only_deleted_after_confirmation(client, scene):
    match_id, striker_id = scene["match"]["id"], scene["striker"]["id"]
    observation = create_observation(client, [striker_id], match_id=match_id)
    refused = client.delete(f"/api/matches/{match_id}")
    assert refused.status_code == 409
    assert refused.json()["dependencies"]["observations"] == 1
    assert client.get(f"/api/observations/{observation['id']}").status_code == 200

    assert client.delete(f"/api/matches/{match_id}", params={"cascade": True}).status_code == 204
    assert client.get(f"/api/observations/{observation['id']}").status_code == 404
    assert client.get(f"/api/players/{striker_id}").status_code == 200


def test_removing_a_video_link_keeps_the_observation_and_its_time(client, scene):
    observation = create_observation(client, [scene["striker"]["id"]], match_id=scene["match"]["id"],
                                     video_reference_id=scene["video"]["id"], video_time_seconds=612.5)
    assert client.delete(f"/api/videos/{scene['video']['id']}").status_code == 204
    after = client.get(f"/api/observations/{observation['id']}").json()
    assert after["video_reference_id"] is None
    assert after["video_time_seconds"] == 612.5
