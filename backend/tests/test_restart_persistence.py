"""Acceptance test A: create records, restart the application, they are still there.

This starts the REAL server as a separate process (twice), so it tests the whole
chain: uvicorn, startup migrations, the API, the SQLite file and the saved
frame pictures on disk.
"""
import base64
import urllib.request

from tests.helpers import TINY_PNG, sample_diagram
from tests.live_server import LiveServer, free_port


def test_records_survive_an_application_restart(tmp_path):
    port = free_port()

    with LiveServer(tmp_path, port) as first_run:
        player = first_run.request("POST", "/api/players", {
            "full_name": "Persistent Example", "primary_position": "ST", "current_team": "Northside FC"})
        match = first_run.request("POST", "/api/matches", {
            "home_team": "Northside FC", "away_team": "Riverton United", "match_date": "2026-03-08"})
        observation = first_run.request("POST", "/api/observations", {
            "player_ids": [player["id"]], "match_id": match["id"], "video_time_seconds": 612.5,
            "category": "Off-ball movement", "notes": "Saved before the restart.", "snapshot": sample_diagram()})
    assert (tmp_path / "football.db").is_file()

    # A completely new process: nothing is left in memory from the first run.
    with LiveServer(tmp_path, port) as second_run:
        listed = second_run.request("GET", "/api/players")
        fetched = second_run.request("GET", f"/api/players/{player['id']}")
        reloaded = second_run.request("GET", f"/api/observations/{observation['id']}")
        with_picture = reloaded["snapshots"][0]["frame_image_url"]
        with urllib.request.urlopen(second_run.url + with_picture, timeout=10) as response:
            picture = response.read()

    assert [entry["full_name"] for entry in listed] == ["Persistent Example"]
    assert fetched["primary_position"] == "ST"
    assert fetched["current_team"]["name"] == "Northside FC"
    assert fetched["created_at"] == player["created_at"]

    # The observation, its timestamp, its diagram and the frame picture all came back.
    assert (reloaded["video_time_seconds"], reloaded["notes"]) == (612.5, "Saved before the restart.")
    assert reloaded["match"]["id"] == match["id"]
    saved_shapes = reloaded["snapshots"][0]["annotations"]
    sent_shapes = sample_diagram()["annotations"]
    assert [(s["uid"], s["points"]) for s in saved_shapes] == [(s["uid"], s["points"]) for s in sent_shapes]
    assert picture == base64.b64decode(TINY_PNG.split(",")[1])
