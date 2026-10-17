"""Video references: the app must say honestly what it can and cannot play."""
import pytest

from services import video_service
from tests.helpers import create_match


@pytest.mark.parametrize("url, expected", [
    ("https://www.youtube.com/watch?v=abcdefghijk", "abcdefghijk"),
    ("https://youtu.be/abcdefghijk?t=95", "abcdefghijk"),
    ("https://m.youtube.com/watch?v=abcdefghijk&list=PL1", "abcdefghijk"),
    ("https://www.youtube.com/embed/abcdefghijk", "abcdefghijk"),
    ("https://www.youtube.com/shorts/abcdefghijk", "abcdefghijk"),
    ("https://www.youtube.com/watch?v=tooshort", None),
    ("https://www.youtube.com/channel/abcdefghijk", None),
    ("https://example.com/watch?v=abcdefghijk", None),
])
def test_youtube_ids_are_recognised(url, expected):
    assert video_service.youtube_video_id(url) == expected


@pytest.mark.parametrize("location, expected", [
    ("/Users/someone/Movies/match.mp4", "local_file"),
    ("https://example.com/clips/goal.MP4", "direct_url"),
    ("https://example.com/clips/goal.webm?token=1", "direct_url"),
    ("https://youtu.be/abcdefghijk", "youtube"),
    ("https://example.com/watch/full-match", "external_link"),
])
def test_the_kind_of_a_video_is_worked_out_from_its_location(location, expected):
    assert video_service.infer_kind(location) == expected


def test_pasted_paths_are_tidied():
    assert video_service.clean_location('  "/Users/someone/My Videos/match.mp4" ') == "/Users/someone/My Videos/match.mp4"
    assert video_service.clean_location("/Users/someone/My\\ Videos/match.mp4") == "/Users/someone/My Videos/match.mp4"
    assert video_service.clean_location("  https://example.com/a.mp4 ") == "https://example.com/a.mp4"


def _add_video(client, match_id, **payload):
    return client.post(f"/api/matches/{match_id}/videos", json=payload)


def test_a_local_video_file_is_playable_and_streamable(client, tmp_path):
    video_file = tmp_path / "first half.mp4"
    video_file.write_bytes(bytes(range(256)) * 40)  # 10,240 bytes standing in for a video
    match = create_match(client)

    response = _add_video(client, match["id"], location=str(video_file), label="First half")
    assert response.status_code == 201, response.text
    video = response.json()
    assert video["kind"] == "local_file"
    assert video["playback"]["mode"] == "html5"
    assert video["playback"]["available"] is True
    assert video["playback"]["can_read_time"] is True
    assert video["playback"]["can_capture_frames"] == "yes"
    assert video["playback"]["source_url"] == f"/api/videos/{video['id']}/stream"

    whole = client.get(video["playback"]["source_url"])
    assert whole.status_code == 200
    assert whole.headers["content-type"] == "video/mp4"
    assert whole.content == video_file.read_bytes()

    # The player seeks by asking for byte ranges; without this a long video cannot be scrubbed.
    part = client.get(video["playback"]["source_url"], headers={"Range": "bytes=100-199"})
    assert part.status_code == 206
    assert part.headers["content-range"] == "bytes 100-199/10240"
    assert part.content == video_file.read_bytes()[100:200]

    assert [v["label"] for v in client.get(f"/api/matches/{match['id']}").json()["videos"]] == ["First half"]


def test_a_missing_file_is_reported_not_hidden(client, tmp_path):
    match = create_match(client)
    video = _add_video(client, match["id"], location=str(tmp_path / "not-here.mp4")).json()
    assert video["playback"]["mode"] == "none"
    assert video["playback"]["available"] is False
    assert "not at this path" in video["playback"]["explanation"]
    assert client.get(f"/api/videos/{video['id']}/stream").status_code == 404


def test_a_file_the_browser_cannot_play_is_a_reference_only(client, tmp_path):
    mkv = tmp_path / "match.mkv"
    mkv.write_bytes(b"not really a video")
    match = create_match(client)
    video = _add_video(client, match["id"], location=str(mkv)).json()
    assert video["kind"] == "local_file"
    assert video["playback"]["mode"] == "none"
    assert ".mkv" in video["playback"]["explanation"]
    # And the app refuses to serve it, so the stream route cannot be used to read other files.
    assert client.get(f"/api/videos/{video['id']}/stream").status_code == 422


def test_web_videos_are_described_honestly(client):
    match = create_match(client)

    youtube = _add_video(client, match["id"], location="https://www.youtube.com/watch?v=abcdefghijk").json()
    assert youtube["kind"] == "youtube"
    assert youtube["playback"]["mode"] == "embed"
    assert youtube["playback"]["source_url"] == "https://www.youtube-nocookie.com/embed/abcdefghijk"
    assert youtube["playback"]["can_read_time"] is True  # through YouTube's own player messages
    assert youtube["playback"]["can_capture_frames"] == "depends"  # only as a screenshot, pasted or shared by the browser
    assert client.get(f"/api/videos/{youtube['id']}/stream").status_code == 422

    direct = _add_video(client, match["id"], location="https://example.com/clips/goal.mp4").json()
    assert direct["kind"] == "direct_url"
    assert direct["playback"]["mode"] == "html5"
    assert direct["playback"]["can_capture_frames"] == "depends"

    link = _add_video(client, match["id"], location="https://example.com/watch/full-match").json()
    assert link["kind"] == "external_link"
    assert link["playback"]["mode"] == "window"  # watched in its own window; the picture comes from sharing it
    assert link["playback"]["source_url"] == "https://example.com/watch/full-match"
    assert link["playback"]["can_read_time"] is False
    assert link["playback"]["can_capture_frames"] == "depends"
    assert "window of its own" in link["playback"]["explanation"]


@pytest.mark.parametrize("payload", [
    {"location": "match.mp4"},  # not a full path
    {"location": "javascript:alert(1)"},
    {"location": "https://example.com/page", "kind": "youtube"},  # declared kind does not fit
    {"location": "https://example.com/a.mp4", "kind": "local_file"},
    {"location": "/Users/someone/match.mp4", "kind": "direct_url"},
    {"location": "   "},
])
def test_invalid_video_references_are_rejected(client, payload):
    match = create_match(client)
    assert _add_video(client, match["id"], **payload).status_code == 422
    assert client.get(f"/api/matches/{match['id']}").json()["videos"] == []


def test_video_rules(client, tmp_path):
    match = create_match(client)
    assert _add_video(client, 999, location="https://youtu.be/abcdefghijk").status_code == 404
    video = _add_video(client, match["id"], location="https://youtu.be/abcdefghijk").json()
    assert video["label"] == "Full match"  # the default label
    assert _add_video(client, match["id"], location="https://youtu.be/abcdefghijk").status_code == 409

    updated = client.put(f"/api/videos/{video['id']}", json={"location": "https://example.com/clip.webm",
                                                             "label": "Highlights"})
    assert updated.status_code == 200
    assert (updated.json()["kind"], updated.json()["label"]) == ("direct_url", "Highlights")

    assert client.delete(f"/api/videos/{video['id']}").status_code == 204
    assert client.get(f"/api/videos/{video['id']}").status_code == 404
