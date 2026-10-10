"""Matches, their lineups and their video references."""
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from errors import Conflict, Invalid
from models import Match, MatchAppearance, Observation, Player, Team, VideoReference
from schemas.match_schema import AppearanceIn, MatchIn, VideoIn
from services import reference_service, video_service
from services.common import get_or_404, like_pattern


def _refuse_duplicate(db: Session, match: Match, exclude_id: int | None = None) -> None:
    if match.match_date is None:
        return  # without a date we cannot tell two meetings of the same teams apart
    statement = select(Match).where(Match.home_team_id == match.home_team.id,
                                    Match.away_team_id == match.away_team.id,
                                    Match.match_date == match.match_date)
    if exclude_id is not None:
        statement = statement.where(Match.id != exclude_id)
    twin = db.scalars(statement).first()
    if twin is not None:
        raise Conflict(f"{twin.title} on {twin.match_date.isoformat()} is already recorded (match #{twin.id}).",
                       existing_match_id=twin.id)


def _apply(db: Session, match: Match, data: MatchIn) -> None:
    home = reference_service.get_or_create_team(db, data.home_team)
    away = reference_service.get_or_create_team(db, data.away_team)
    if home.id == away.id:
        raise Invalid("Home and away team must be different.")
    match.home_team, match.away_team = home, away
    match.competition = reference_service.get_or_create_competition(db, data.competition)
    match.season = reference_service.get_or_create_season(db, data.season)
    for field in ("match_date", "venue", "home_score", "away_score", "home_formation", "away_formation", "notes"):
        setattr(match, field, getattr(data, field))


def create_match(db: Session, data: MatchIn, commit: bool = True) -> Match:
    match = Match()
    _apply(db, match, data)
    _refuse_duplicate(db, match)
    db.add(match)
    if commit:
        db.commit()
    else:
        db.flush()  # used by the CSV import, which commits once for the whole file
    return match


def update_match(db: Session, match_id: int, data: MatchIn) -> Match:
    match = get_or_404(db, Match, match_id, "Match")
    # Lineups remember a TEAM, not "home"/"away". If a team is replaced here,
    # each player must follow their side to the new team.
    sides = {appearance.id: appearance.side for appearance in match.appearances}
    _apply(db, match, data)
    _refuse_duplicate(db, match, exclude_id=match_id)
    for appearance in match.appearances:
        appearance.team_id = match.home_team.id if sides[appearance.id] == "home" else match.away_team.id
    db.commit()
    return match


def list_matches(db: Session, team_id: int | None = None, competition_id: int | None = None,
                 season_id: int | None = None, date_from: date | None = None, date_to: date | None = None,
                 q: str | None = None) -> list[tuple[Match, int, int]]:
    """Matches, newest first (undated last), each with its observation and video counts."""
    statement = select(Match).order_by(Match.match_date.desc().nulls_last(), Match.id.desc())
    if team_id is not None:
        statement = statement.where(or_(Match.home_team_id == team_id, Match.away_team_id == team_id))
    if competition_id is not None:
        statement = statement.where(Match.competition_id == competition_id)
    if season_id is not None:
        statement = statement.where(Match.season_id == season_id)
    if date_from is not None:
        statement = statement.where(Match.match_date >= date_from)
    if date_to is not None:
        statement = statement.where(Match.match_date <= date_to)
    if q:
        pattern = like_pattern(q)
        matching_teams = select(Team.id).where(Team.name.like(pattern, escape="\\"))
        statement = statement.where(or_(Match.home_team_id.in_(matching_teams), Match.away_team_id.in_(matching_teams),
                                        Match.venue.like(pattern, escape="\\")))
    matches = db.scalars(statement).all()

    observation_counts = dict(db.execute(
        select(Observation.match_id, func.count()).where(Observation.match_id.is_not(None))
        .group_by(Observation.match_id)).all())
    video_counts = dict(db.execute(
        select(VideoReference.match_id, func.count()).group_by(VideoReference.match_id)).all())
    return [(match, observation_counts.get(match.id, 0), video_counts.get(match.id, 0)) for match in matches]


def observation_count(db: Session, match_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Observation).where(Observation.match_id == match_id)) or 0


# ── Lineups ──────────────────────────────────────────────────────────────────
def _appearance_fields(data: AppearanceIn) -> dict:
    return data.model_dump(exclude={"player_id", "side"})


def add_appearance(db: Session, match_id: int, data: AppearanceIn) -> MatchAppearance:
    match = get_or_404(db, Match, match_id, "Match")
    player = get_or_404(db, Player, data.player_id, "Player")
    already = db.scalar(select(MatchAppearance).where(MatchAppearance.match_id == match_id,
                                                      MatchAppearance.player_id == player.id))
    if already is not None:
        raise Conflict(f"{player.full_name} is already in this match's lineup.")
    appearance = MatchAppearance(
        match=match, player=player,
        team_id=match.home_team_id if data.side == "home" else match.away_team_id,
        **_appearance_fields(data),
    )
    db.add(appearance)
    db.commit()
    return appearance


def update_appearance(db: Session, appearance_id: int, data: AppearanceIn) -> MatchAppearance:
    appearance = get_or_404(db, MatchAppearance, appearance_id, "Lineup entry")
    if data.player_id != appearance.player_id:
        raise Invalid("A lineup entry belongs to one player. Remove it and add the other player instead.")
    match = appearance.match
    appearance.team_id = match.home_team_id if data.side == "home" else match.away_team_id
    for field, value in _appearance_fields(data).items():
        setattr(appearance, field, value)
    db.commit()
    return appearance


def remove_appearance(db: Session, appearance_id: int) -> None:
    db.delete(get_or_404(db, MatchAppearance, appearance_id, "Lineup entry"))
    db.commit()


# ── Video references ─────────────────────────────────────────────────────────
def _refuse_same_video_twice(db: Session, match_id: int, location: str, exclude_id: int | None = None) -> None:
    statement = select(VideoReference).where(VideoReference.match_id == match_id,
                                             VideoReference.location == location)
    if exclude_id is not None:
        statement = statement.where(VideoReference.id != exclude_id)
    if db.scalars(statement).first() is not None:
        raise Conflict("This video is already linked to the match.")


def add_video(db: Session, match_id: int, data: VideoIn) -> VideoReference:
    get_or_404(db, Match, match_id, "Match")
    location, kind = video_service.validate(data.location, data.kind)
    _refuse_same_video_twice(db, match_id, location)
    video = VideoReference(match_id=match_id, label=data.label or "Full match", kind=kind,
                           location=location, notes=data.notes)
    db.add(video)
    db.commit()
    return video


def update_video(db: Session, video_id: int, data: VideoIn) -> VideoReference:
    video = get_or_404(db, VideoReference, video_id, "Video")
    location, kind = video_service.validate(data.location, data.kind)
    _refuse_same_video_twice(db, video.match_id, location, exclude_id=video_id)
    video.label, video.kind, video.location, video.notes = data.label or "Full match", kind, location, data.notes
    db.commit()
    return video


def remove_video(db: Session, video_id: int) -> None:
    """Remove a video link. Observations made from it keep their timestamp (see observation_model.py)."""
    db.delete(get_or_404(db, VideoReference, video_id, "Video"))
    db.commit()
