"""API routes for matches, lineups and video references (including streaming a local video)."""
from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db
from models import Match, VideoReference
from schemas.match_schema import (
    AppearanceIn, AppearanceOut, MatchDetail, MatchIn, MatchListItem, MatchOut, VideoIn, VideoOut,
)
from services import deletion_service, match_service, video_service
from services.common import get_or_404

router = APIRouter(prefix="/api", tags=["matches"])

_VIDEO_MEDIA_TYPES = {
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
    ".webm": "video/webm", ".ogv": "video/ogg", ".ogg": "video/ogg",
}


def _video_out(video: VideoReference) -> dict:
    return {"id": video.id, "match_id": video.match_id, "label": video.label, "kind": video.kind,
            "location": video.location, "notes": video.notes, "playback": video_service.describe_playback(video)}


def _lineup_order(appearance) -> tuple:
    """Home side first, starters before substitutes, then by shirt number."""
    return (appearance.side != "home", not appearance.is_starter, appearance.shirt_number or 999,
            appearance.player.full_name)


# ── Matches ──────────────────────────────────────────────────────────────────
@router.get("/matches", response_model=list[MatchListItem])
def list_matches(team_id: int | None = None, competition_id: int | None = None, season_id: int | None = None,
                 date_from: date | None = None, date_to: date | None = None, q: str | None = None,
                 db: Session = Depends(get_db)):
    rows = match_service.list_matches(db, team_id=team_id, competition_id=competition_id, season_id=season_id,
                                      date_from=date_from, date_to=date_to, q=q)
    return [
        {**MatchOut.model_validate(match).model_dump(), "observation_count": observations, "video_count": videos}
        for match, observations, videos in rows
    ]


@router.post("/matches", response_model=MatchOut, status_code=201)
def create_match(data: MatchIn, db: Session = Depends(get_db)):
    return match_service.create_match(db, data)


@router.get("/matches/{match_id}", response_model=MatchDetail)
def get_match(match_id: int, db: Session = Depends(get_db)):
    match = get_or_404(db, Match, match_id, "Match")
    return {
        **MatchOut.model_validate(match).model_dump(),
        "appearances": [AppearanceOut.model_validate(a) for a in sorted(match.appearances, key=_lineup_order)],
        "videos": [_video_out(video) for video in match.videos],
        "observation_count": match_service.observation_count(db, match_id),
    }


@router.put("/matches/{match_id}", response_model=MatchOut)
def update_match(match_id: int, data: MatchIn, db: Session = Depends(get_db)):
    return match_service.update_match(db, match_id, data)


@router.get("/matches/{match_id}/dependencies")
def match_dependencies(match_id: int, db: Session = Depends(get_db)):
    """What is attached to a match. The interface shows this before asking to confirm a delete."""
    get_or_404(db, Match, match_id, "Match")
    return deletion_service.match_dependencies(db, match_id)


@router.delete("/matches/{match_id}", status_code=204)
def delete_match(match_id: int, cascade: bool = False, db: Session = Depends(get_db)):
    deletion_service.delete_match(db, match_id, cascade=cascade)


# ── Lineups ──────────────────────────────────────────────────────────────────
@router.post("/matches/{match_id}/appearances", response_model=AppearanceOut, status_code=201)
def add_appearance(match_id: int, data: AppearanceIn, db: Session = Depends(get_db)):
    return match_service.add_appearance(db, match_id, data)


@router.put("/appearances/{appearance_id}", response_model=AppearanceOut)
def update_appearance(appearance_id: int, data: AppearanceIn, db: Session = Depends(get_db)):
    return match_service.update_appearance(db, appearance_id, data)


@router.delete("/appearances/{appearance_id}", status_code=204)
def remove_appearance(appearance_id: int, db: Session = Depends(get_db)):
    match_service.remove_appearance(db, appearance_id)


# ── Video references ─────────────────────────────────────────────────────────
@router.post("/matches/{match_id}/videos", response_model=VideoOut, status_code=201)
def add_video(match_id: int, data: VideoIn, db: Session = Depends(get_db)):
    return _video_out(match_service.add_video(db, match_id, data))


@router.get("/videos/{video_id}", response_model=VideoOut)
def get_video(video_id: int, db: Session = Depends(get_db)):
    return _video_out(get_or_404(db, VideoReference, video_id, "Video"))


@router.put("/videos/{video_id}", response_model=VideoOut)
def update_video(video_id: int, data: VideoIn, db: Session = Depends(get_db)):
    return _video_out(match_service.update_video(db, video_id, data))


@router.delete("/videos/{video_id}", status_code=204)
def remove_video(video_id: int, db: Session = Depends(get_db)):
    match_service.remove_video(db, video_id)


@router.get("/videos/{video_id}/stream")
def stream_video(video_id: int, db: Session = Depends(get_db)):
    """Send a local video file to the app's own player.

    Because the video then comes from the same address as the page, the browser
    lets the page read its pixels, which is what makes frame capture possible.
    FileResponse answers "Range" requests, which is how the player jumps around
    in a long video without downloading all of it.
    """
    video = get_or_404(db, VideoReference, video_id, "Video")
    path = video_service.local_file_to_stream(video)
    return FileResponse(
        path,
        media_type=_VIDEO_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"),
        headers={"Cache-Control": "private, max-age=3600"},
    )
