"""Video references: what kind of thing a location is, and what the app can honestly do with it.

A video reference is only ever a path or a link. This module answers, for each
one, "can the app actually play this, read its time, and capture a frame?" and
says so in plain words. The four kinds:

    local_file     a video file on this computer.
                   The app streams it to its own player, so it can pause it, read
                   the exact time and capture the frame. Fully supported.

    direct_url     a web link straight to a video file (ends in .mp4, .webm, ...).
                   Plays in the app's own player if the website allows it. Frame
                   capture depends on that website: browsers refuse to let a page
                   read pixels of a video from another site unless that site
                   explicitly permits it.

    youtube        shown inside YouTube's own embedded player. The app cannot read
                   its time or pixels, and YouTube's terms do not allow drawing
                   over the player. Use the manual workspace (type the time, add
                   a screenshot).

    external_link  any other web page. Just a link to open in a new tab.

Nothing here downloads, converts or unlocks video. Protected streams stay protected.
"""
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import config
from errors import Invalid, NotFound
from models import VideoReference

_YOUTUBE_ID = re.compile(r"[A-Za-z0-9_-]{11}")


def is_web_link(location: str) -> bool:
    return location.lower().startswith(("http://", "https://"))


def clean_location(raw: str) -> str:
    """Tidy a pasted path or link: drop surrounding quotes, expand ~, undo shell-style '\\ '."""
    text = raw.strip().strip("\"'").strip()
    if is_web_link(text):
        return text
    return str(Path(text.replace("\\ ", " ")).expanduser())


def youtube_video_id(url: str) -> str | None:
    """The 11-character video id from any common form of YouTube link, or None."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    for prefix in ("www.", "m.", "music."):
        host = host.removeprefix(prefix)
    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "youtube-nocookie.com"):
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        else:
            parts = parsed.path.strip("/").split("/")
            candidate = parts[1] if len(parts) >= 2 and parts[0] in ("embed", "shorts", "live", "v") else ""
    else:
        return None
    return candidate if _YOUTUBE_ID.fullmatch(candidate) else None


def infer_kind(location: str) -> str:
    """Work out the kind of a (cleaned) location."""
    if not is_web_link(location):
        return "local_file"
    if youtube_video_id(location):
        return "youtube"
    if Path(urlparse(location).path).suffix.lower() in config.VIDEO_EXTENSIONS:
        return "direct_url"
    return "external_link"


def validate(location: str, kind: str | None) -> tuple[str, str]:
    """Clean the location and settle its kind. Raises Invalid when they do not fit together."""
    location = clean_location(location)
    kind = kind or infer_kind(location)
    if kind == "local_file":
        if is_web_link(location):
            raise Invalid("A local file needs a path on this computer, not a web link.")
        if not Path(location).is_absolute():
            raise Invalid("Give the full path of the video file, starting with / "
                          "(for example /Users/you/Movies/match.mp4).")
    else:
        if not is_web_link(location):
            raise Invalid("This kind of video needs a web link starting with http:// or https://")
        if kind == "youtube" and not youtube_video_id(location):
            raise Invalid("That does not look like a link to a YouTube video.")
    return location, kind


def describe_playback(video: VideoReference) -> dict:
    """What the app can do with this video right now, with the reason in plain words."""
    if video.kind == "local_file":
        path = Path(video.location)
        if not path.is_file():
            return _playback("none", None, False, False, "no",
                             "The file is not at this path right now. If it is on an external drive, connect it "
                             "and reload. You can still record observations with the manual workspace.")
        if path.suffix.lower() not in config.VIDEO_EXTENSIONS:
            return _playback("none", None, True, False, "no",
                             f"Browsers cannot play {path.suffix or 'this type of'} files. Convert it to .mp4 "
                             "(H.264 video) and point this reference at the new file. Until then, use the manual "
                             "workspace: type the timestamp and add a screenshot.")
        return _playback("html5", f"/api/videos/{video.id}/stream", True, True, "yes",
                         "Plays in the app. Pause anywhere, press Analyse, and the exact time and frame are captured.")
    if video.kind == "direct_url":
        return _playback("html5", video.location, True, True, "depends",
                         "Plays in the app if the website allows it. Capturing the frame only works when that "
                         "website permits it (a browser security rule). If it does not, you can still draw over "
                         "the paused picture or add a screenshot.")
    if video.kind == "youtube":
        video_id = youtube_video_id(video.location)
        return _playback("embed", f"https://www.youtube-nocookie.com/embed/{video_id}", True, False, "no",
                         "Shown in YouTube's own player. The app cannot read its time or capture its frames, and "
                         "may not draw over it. Pause, type the time shown on the player, and add a screenshot or "
                         "use the tactical pitch.")
    return _playback("none", video.location, True, False, "no",
                     "This is only a link, not a video the app can play. Open it in a new tab, then use the manual "
                     "workspace: type the timestamp and add a screenshot.")


def _playback(mode: str, source_url: str | None, available: bool, can_read_time: bool,
              can_capture_frames: str, explanation: str) -> dict:
    return {"mode": mode, "source_url": source_url, "available": available, "can_read_time": can_read_time,
            "can_capture_frames": can_capture_frames, "explanation": explanation}


def local_file_to_stream(video: VideoReference) -> Path:
    """The file to send to the player, after checking it is a video the app may serve.

    Only files that were registered as a match video AND have a video extension
    are ever served. That keeps this from being a way to read arbitrary files.
    """
    if video.kind != "local_file":
        raise Invalid("Only local video files are streamed by the app.")
    path = Path(video.location)
    if path.suffix.lower() not in config.VIDEO_EXTENSIONS:
        raise Invalid(f"The app does not stream {path.suffix or 'this type of'} files.")
    if not path.is_file():
        raise NotFound("The video file is not at its recorded path right now.")
    return path
