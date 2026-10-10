"""Shortcuts for creating test data through the API, the same way the browser does.

All names here are made up on purpose. Tests must never record invented facts
about real players.
"""


def create_player(client, **overrides) -> dict:
    response = client.post("/api/players", json={"full_name": "Alex Example", **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def create_match(client, **overrides) -> dict:
    payload = {"home_team": "Northside FC", "away_team": "Riverton United", "match_date": "2026-03-08", **overrides}
    response = client.post("/api/matches", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def add_to_lineup(client, match_id: int, player_id: int, side: str = "home", **overrides) -> dict:
    response = client.post(f"/api/matches/{match_id}/appearances",
                           json={"player_id": player_id, "side": side, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def create_assessment(client, player_id: int, **overrides) -> dict:
    payload = {"assessed_on": "2026-03-01", "summary": "Sharp movement in the box.", **overrides}
    response = client.post(f"/api/players/{player_id}/assessments", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def create_observation(client, player_ids: list[int], **overrides) -> dict:
    payload = {"player_ids": player_ids, "category": "Off-ball movement", **overrides}
    response = client.post("/api/observations", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# A real 1 x 1 pixel PNG, as the browser would send a captured frame.
TINY_PNG = ("data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def shape(uid: str, layer: str, kind: str, points: list[list[float]], **extra) -> dict:
    return {"uid": uid, "layer": layer, "kind": kind, "points": points, **extra}


def sample_diagram(**overrides) -> dict:
    """A tactical diagram using both layers: a 1280x720 video frame and the pitch.

    Frame points are fractions of the frame (0-1). Pitch points are metres.
    """
    return {
        "title": "Run behind the left centre-back",
        "frame_width": 1280, "frame_height": 720, "frame_image": TINY_PNG, "frame_source": "video_capture",
        "annotations": [
            # Over the video frame
            shape("f-subject", "frame", "subject", [[0.512, 0.431]], label="9"),
            shape("f-def-1", "frame", "defender", [[0.585, 0.402]]),
            shape("f-ball", "frame", "ball", [[0.31, 0.655]]),
            shape("f-run", "frame", "movement", [[0.512, 0.431], [0.702, 0.365]]),
            shape("f-space", "frame", "zone", [[0.62, 0.28], [0.86, 0.47]], label="Space behind"),
            # On the top-down pitch
            shape("p-subject", "pitch", "subject", [[78.0, 30.5]], label="9"),
            shape("p-mate", "pitch", "attacker", [[66.25, 12.0]], label="11"),
            shape("p-def-1", "pitch", "defender", [[84.0, 27.0]], label="CB"),
            shape("p-def-2", "pitch", "defender", [[84.5, 38.0]], label="CB"),
            shape("p-gk", "pitch", "goalkeeper", [[101.0, 34.0]]),
            shape("p-ball", "pitch", "ball", [[66.9, 12.6]]),
            shape("p-run", "pitch", "movement", [[78.0, 30.5], [92.0, 24.0]],
                  properties={"recorded_movement": True}),
            shape("p-pass", "pitch", "pass", [[66.9, 12.6], [91.0, 23.5]]),
            shape("p-space", "pitch", "zone", [[86.0, 14.0], [100.0, 30.0]],
                  properties={"zone_type": "Space behind the defensive line"}),
            shape("p-angle", "pitch", "angle", [[66.9, 12.6], [78.0, 30.5], [105.0, 34.0]]),
            shape("p-note", "pitch", "text", [[70.0, 50.0]], label="Winger faces forward"),
        ],
        **overrides,
    }
