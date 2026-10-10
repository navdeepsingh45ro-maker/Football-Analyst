"""Tactical snapshots: acceptance test E (a diagram is saved and rebuilt exactly) and the
"all or nothing" rule for saving (part of acceptance test K)."""
import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import config
import database
from main import app
from models import Annotation, Observation, TacticalSnapshot
from tests.helpers import TINY_PNG, create_observation, create_player, sample_diagram, shape


def _count(db, model) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(model))


def _frame_files() -> list[str]:
    return sorted(path.name for path in config.FRAMES_DIR.glob("*"))


# ── E: annotation persistence ────────────────────────────────────────────────
def test_a_diagram_is_saved_and_rebuilt_exactly(client):
    """Several players, the ball, arrows and a highlighted space: save, reload, compare."""
    player = create_player(client)
    sent = sample_diagram()
    created = create_observation(client, [player["id"]], video_time_seconds=612.5, snapshot=sent)
    snapshot_id = created["snapshot_ids"][0]

    # "Reload the application": drop every database connection, then read it all back.
    database.engine.dispose()
    reloaded = client.get(f"/api/observations/{created['id']}").json()["snapshots"][0]

    assert reloaded["id"] == snapshot_id
    assert (reloaded["frame_width"], reloaded["frame_height"]) == (1280, 720)  # the original frame's size
    assert (reloaded["pitch_length_m"], reloaded["pitch_width_m"]) == (105.0, 68.0)
    assert reloaded["frame_source"] == "video_capture"
    assert reloaded["title"] == "Run behind the left centre-back"

    # Every shape comes back in the same order with identical coordinates.
    assert len(reloaded["annotations"]) == len(sent["annotations"]) == 16
    for order, (stored, original) in enumerate(zip(reloaded["annotations"], sent["annotations"])):
        assert stored["uid"] == original["uid"]
        assert stored["layer"] == original["layer"]
        assert stored["kind"] == original["kind"]
        assert stored["points"] == original["points"], original["uid"]  # exact, not "close"
        assert stored["label"] == original.get("label")
        assert stored["properties"] == original.get("properties", {})
        assert stored["z_index"] == order

    kinds = {(a["layer"], a["kind"]) for a in reloaded["annotations"]}
    assert {("pitch", "subject"), ("pitch", "attacker"), ("pitch", "defender"), ("pitch", "goalkeeper"),
            ("pitch", "ball"), ("pitch", "movement"), ("pitch", "pass"), ("pitch", "zone"), ("pitch", "angle"),
            ("pitch", "text"), ("frame", "subject"), ("frame", "defender"), ("frame", "ball"),
            ("frame", "movement"), ("frame", "zone")} == kinds

    # The saved frame picture is served back byte for byte.
    picture = client.get(reloaded["frame_image_url"])
    assert picture.status_code == 200
    assert picture.headers["content-type"] == "image/png"
    assert picture.content == base64.b64decode(TINY_PNG.split(",")[1])


def test_coordinates_are_stored_in_layer_units_never_in_screen_pixels(client):
    """What makes diagrams resize-proof: nothing saved depends on how big the screen was."""
    player = create_player(client)
    created = create_observation(client, [player["id"]], snapshot=sample_diagram())
    for annotation in created["snapshots"][0]["annotations"]:
        for x, y in annotation["points"]:
            if annotation["layer"] == "frame":
                assert 0 <= x <= 1 and 0 <= y <= 1  # fractions of the 1280x720 frame
            else:
                assert -5 <= x <= 110 and -5 <= y <= 73  # metres on the 105x68 pitch


def test_saving_again_replaces_the_shapes_and_keeps_their_identity(client, db):
    player = create_player(client)
    created = create_observation(client, [player["id"]], snapshot=sample_diagram())
    snapshot = created["snapshots"][0]
    picture_before = client.get(snapshot["frame_image_url"]).content

    # The editor sends the whole diagram again: one shape moved, one removed, one added.
    edited = [a for a in sample_diagram()["annotations"] if a["uid"] != "p-note"]
    next(a for a in edited if a["uid"] == "p-subject")["points"] = [[80.0, 31.25]]
    edited.append(shape("p-new", "pitch", "line", [[84.0, 20.0], [84.5, 45.0]], label="Defensive line"))
    response = client.put(f"/api/snapshots/{snapshot['id']}",
                          json={"title": "Edited", "frame_width": 1280, "frame_height": 720, "annotations": edited})
    assert response.status_code == 200, response.text

    after = client.get(f"/api/snapshots/{snapshot['id']}").json()
    by_uid = {a["uid"]: a for a in after["annotations"]}
    assert by_uid["p-subject"]["points"] == [[80.0, 31.25]]
    assert "p-note" not in by_uid and by_uid["p-new"]["label"] == "Defensive line"
    assert by_uid["f-run"]["points"] == [[0.512, 0.431], [0.702, 0.365]]  # untouched shapes are unchanged
    assert _count(db, Annotation) == len(edited)  # no leftovers from the first save

    # No new picture was sent, so the stored one is kept.
    assert after["frame_image_url"] == snapshot["frame_image_url"]
    assert client.get(after["frame_image_url"]).content == picture_before
    assert len(_frame_files()) == 1


def test_replacing_or_removing_the_picture_cleans_up_the_old_file(client):
    player = create_player(client)
    snapshot = create_observation(client, [player["id"]], snapshot=sample_diagram())["snapshots"][0]
    first_file = _frame_files()
    body = {"frame_width": 1280, "frame_height": 720, "annotations": []}

    replaced = client.put(f"/api/snapshots/{snapshot['id']}", json={**body, "frame_image": TINY_PNG}).json()
    assert replaced["frame_image_url"] != snapshot["frame_image_url"]  # a new address, so no stale picture
    assert len(_frame_files()) == 1 and _frame_files() != first_file

    removed = client.put(f"/api/snapshots/{snapshot['id']}", json={**body, "keep_frame_image": False}).json()
    assert removed["frame_image_url"] is None
    assert _frame_files() == []
    assert client.get(f"/api/snapshots/{snapshot['id']}/frame").status_code == 404


def test_shapes_can_be_drawn_over_a_video_whose_frame_could_not_be_captured(client):
    """Frame size known, no picture: allowed (e.g. a video on a site that forbids capture)."""
    player = create_player(client)
    diagram = sample_diagram(frame_image=None, frame_source=None)
    snapshot = create_observation(client, [player["id"]], snapshot=diagram)["snapshots"][0]
    assert snapshot["frame_image_url"] is None
    assert (snapshot["frame_width"], snapshot["frame_height"]) == (1280, 720)
    assert sum(1 for a in snapshot["annotations"] if a["layer"] == "frame") == 5


# ── K: a diagram is saved completely or not at all ───────────────────────────
@pytest.mark.parametrize("why, change", [
    ("frame point outside the frame", {"annotations": [shape("a", "frame", "ball", [[1.2, 0.5]])]}),
    ("frame point given in pixels", {"annotations": [shape("a", "frame", "ball", [[640, 360]])]}),
    ("pitch point far off the pitch", {"annotations": [shape("a", "pitch", "ball", [[150, 34]])]}),
    ("frame shapes without a frame size", {"frame_width": None, "frame_height": None, "frame_image": None,
                                           "annotations": [shape("a", "frame", "ball", [[0.5, 0.5]])]}),
    ("only one frame dimension", {"frame_height": None, "frame_image": None, "annotations": []}),
    ("an arrow with one point", {"annotations": [shape("a", "pitch", "movement", [[10, 10]])]}),
    ("an angle with two points", {"annotations": [shape("a", "pitch", "angle", [[10, 10], [20, 20]])]}),
    ("a marker with two points", {"annotations": [shape("a", "pitch", "defender", [[10, 10], [20, 20]])]}),
    ("an unknown kind of shape", {"annotations": [shape("a", "pitch", "dragon", [[10, 10]])]}),
    ("an unknown layer", {"annotations": [shape("a", "sky", "ball", [[10, 10]])]}),
    ("two shapes with the same uid", {"annotations": [shape("a", "pitch", "ball", [[10, 10]]),
                                                      shape("a", "pitch", "defender", [[20, 20]])]}),
    ("two recorded movements", {"annotations": [
        shape("a", "pitch", "movement", [[10, 10], [20, 20]], properties={"recorded_movement": True}),
        shape("b", "pitch", "movement", [[30, 30], [40, 40]], properties={"recorded_movement": True})]}),
    ("a marker for a player who does not exist", {"annotations": [shape("a", "pitch", "subject", [[10, 10]],
                                                                        player_id=999)]}),
    ("a pitch far too long", {"pitch_length_m": 200}),
    ("a picture that is not base64", {"frame_image": "data:image/png;base64,@@not-base64@@"}),
    ("a text file dressed up as a picture", {"frame_image": "data:image/png;base64," +
                                             base64.b64encode(b"just some text").decode()}),
    ("a picture that is not a data URL", {"frame_image": "https://example.com/frame.png"}),
])
def test_an_invalid_diagram_saves_nothing_at_all(client, db, why, change):
    player = create_player(client)
    response = client.post("/api/observations", json={
        "player_ids": [player["id"]], "category": "Positioning", "snapshot": sample_diagram(**change)})
    assert response.status_code == 422, f"{why}: {response.text}"
    # Not the observation, not the diagram, not a single shape, not the picture.
    assert _count(db, Observation) == 0, why
    assert _count(db, TacticalSnapshot) == 0, why
    assert _count(db, Annotation) == 0, why
    assert _frame_files() == [], why


def test_an_oversized_picture_is_refused(client, db, monkeypatch):
    monkeypatch.setattr(config, "MAX_FRAME_BYTES", 10)
    player = create_player(client)
    response = client.post("/api/observations", json={
        "player_ids": [player["id"]], "category": "Positioning", "snapshot": sample_diagram()})
    assert response.status_code == 422
    assert "larger than" in response.json()["detail"]
    assert _count(db, Observation) == 0 and _frame_files() == []


def test_a_failed_database_save_leaves_no_picture_behind(db, monkeypatch):
    """The picture is written before the database commit. If the commit fails, it must be removed again."""
    client = TestClient(app, raise_server_exceptions=False)
    player = create_player(client)

    def failing_commit(self):
        raise RuntimeError("the disk is full")

    monkeypatch.setattr(Session, "commit", failing_commit)
    response = client.post("/api/observations", json={
        "player_ids": [player["id"]], "category": "Positioning", "snapshot": sample_diagram()})
    monkeypatch.undo()

    assert response.status_code == 500
    assert "disk is full" not in response.text  # internal details are not shown to the user
    assert _frame_files() == []
    assert _count(db, Observation) == 0 and _count(db, TacticalSnapshot) == 0 and _count(db, Annotation) == 0


# ── Markers, lists and deletion ──────────────────────────────────────────────
def test_a_marker_can_stand_for_a_real_player(client):
    striker = create_player(client, full_name="Sam Finisher")
    winger = create_player(client, full_name="Lee Wide")
    diagram = {"annotations": [shape("s", "pitch", "subject", [[78, 30]], player_id=striker["id"], label="9"),
                               shape("w", "pitch", "attacker", [[66, 12]], player_id=winger["id"])]}
    observation = create_observation(client, [winger["id"], striker["id"]], snapshot=diagram)
    assert [a["player_id"] for a in observation["snapshots"][0]["annotations"]] == [striker["id"], winger["id"]]

    # If that player is later deleted, the marker stays on the diagram without the link.
    client.delete(f"/api/players/{striker['id']}", params={"cascade": True})
    after = client.get(f"/api/observations/{observation['id']}").json()
    assert [a["player_id"] for a in after["snapshots"][0]["annotations"]] == [None, winger["id"]]


def test_deleting_an_observation_removes_its_diagram_shapes_and_picture(client, db):
    player = create_player(client)
    observation = create_observation(client, [player["id"]], snapshot=sample_diagram())
    assert len(_frame_files()) == 1
    assert client.delete(f"/api/observations/{observation['id']}").status_code == 204
    assert _count(db, TacticalSnapshot) == 0 and _count(db, Annotation) == 0
    assert _frame_files() == []


def test_a_further_diagram_can_be_added_and_removed(client, db):
    player = create_player(client)
    observation = create_observation(client, [player["id"]], snapshot=sample_diagram())
    second = client.post(f"/api/observations/{observation['id']}/snapshots",
                         json={"title": "A moment later",
                               "annotations": [shape("b", "pitch", "ball", [[92, 24]])]})
    assert second.status_code == 201
    assert client.get(f"/api/observations/{observation['id']}").json()["snapshot_ids"] == [
        observation["snapshot_ids"][0], second.json()["id"]]
    assert client.post("/api/observations/999/snapshots", json={"annotations": []}).status_code == 404

    assert client.delete(f"/api/snapshots/{second.json()['id']}").status_code == 204
    assert _count(db, TacticalSnapshot) == 1
    assert len(_frame_files()) == 1  # the first diagram's picture is untouched


def test_standalone_pitch_diagrams_and_per_player_lists(client):
    player = create_player(client)
    drill = client.post("/api/snapshots", json={
        "title": "Third-man run pattern",
        "annotations": [shape("a", "pitch", "attacker", [[40, 30]]), shape("b", "pitch", "ball", [[41, 31]])]})
    assert drill.status_code == 201
    assert drill.json()["observation_id"] is None

    observed = create_observation(client, [player["id"]], video_time_seconds=612.5, snapshot=sample_diagram())

    standalone = client.get("/api/snapshots").json()
    assert [(d["title"], d["has_pitch_layer"], d["has_frame_layer"], d["shape_count"]) for d in standalone] == [
        ("Third-man run pattern", True, False, 2)]

    mine = client.get(f"/api/players/{player['id']}/diagrams").json()
    assert len(mine) == 1
    assert mine[0]["observation_id"] == observed["id"]
    assert mine[0]["observation_category"] == "Off-ball movement"
    assert mine[0]["video_time_seconds"] == 612.5
    assert mine[0]["has_frame_layer"] and mine[0]["has_pitch_layer"] and mine[0]["shape_count"] == 16
    assert client.get(f"/api/players/{player['id']}").json()["counts"]["diagrams"] == 1
    assert client.get("/api/players/999/diagrams").status_code == 404
