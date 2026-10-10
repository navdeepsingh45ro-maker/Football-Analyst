"""The dashboard: counts, recent work and what is still waiting, all read from your records.

Nothing here is invented or estimated. Every number is a COUNT of rows, and
every "recent" list is ordered by when a real record was last saved. An empty
database gives an empty dashboard.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import (
    CoachingNote, Match, Observation, ObservationPlayer, Player, ScoutingAssessment, TacticalSnapshot,
    TrainingIdea, VideoReference,
)
from services import observation_service


def _count(db: Session, model) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def _recent_players(db: Session, limit: int) -> list[dict]:
    """Players ordered by the latest observation or assessment saved about them."""
    latest: dict[int, tuple] = {}
    observed = db.execute(
        select(ObservationPlayer.player_id, func.max(Observation.updated_at))
        .join(Observation, Observation.id == ObservationPlayer.observation_id)
        .group_by(ObservationPlayer.player_id)).all()
    assessed = db.execute(
        select(ScoutingAssessment.player_id, func.max(ScoutingAssessment.updated_at))
        .group_by(ScoutingAssessment.player_id)).all()
    for rows, what in ((observed, "observation"), (assessed, "assessment")):
        for player_id, when in rows:
            if player_id not in latest or when > latest[player_id][0]:
                latest[player_id] = (when, what)

    newest = sorted(latest.items(), key=lambda item: item[1][0], reverse=True)[:limit]
    players = {player.id: player for player in db.scalars(
        select(Player).where(Player.id.in_([player_id for player_id, _ in newest])))}
    return [{"id": player_id, "full_name": players[player_id].full_name,
             "primary_position": players[player_id].primary_position,
             "last_activity": when, "activity": what} for player_id, (when, what) in newest]


def _recent_matches(db: Session, limit: int) -> list[dict]:
    """Matches ordered by the latest observation saved for them."""
    rows = db.execute(
        select(Observation.match_id, func.max(Observation.updated_at).label("latest"), func.count())
        .where(Observation.match_id.is_not(None)).group_by(Observation.match_id)
        .order_by(func.max(Observation.updated_at).desc()).limit(limit)).all()
    matches = {match.id: match for match in db.scalars(
        select(Match).where(Match.id.in_([match_id for match_id, _, _ in rows])))}
    return [{"match": matches[match_id], "observation_count": count, "last_activity": when}
            for match_id, when, count in rows]


def summary(db: Session) -> dict:
    analysed = select(Observation.match_id).where(Observation.match_id.is_not(None))
    assessed = select(ScoutingAssessment.player_id)
    with_video = select(VideoReference.match_id)

    waiting_matches = db.scalars(
        select(Match).where(Match.id.not_in(analysed), Match.id.in_(with_video))
        .order_by(Match.match_date.desc().nulls_last(), Match.id.desc()).limit(8)).all()
    unassessed_players = db.scalars(
        select(Player).where(Player.id.not_in(assessed)).order_by(Player.full_name).limit(8)).all()
    open_notes = db.scalars(
        select(CoachingNote).where(CoachingNote.status == "open").order_by(CoachingNote.created_at).limit(12)).all()
    latest_observations = db.scalars(
        select(Observation).order_by(Observation.updated_at.desc(), Observation.id.desc()).limit(8)).all()

    return {
        "counts": {
            "players": _count(db, Player),
            "matches": _count(db, Match),
            "matches_analysed": db.scalar(select(func.count(func.distinct(Observation.match_id)))) or 0,
            "observations": _count(db, Observation),
            "diagrams": _count(db, TacticalSnapshot),
            "assessments": _count(db, ScoutingAssessment),
            "notes": _count(db, CoachingNote) + _count(db, TrainingIdea),
        },
        "recent_players": _recent_players(db, 6),
        "recent_matches": _recent_matches(db, 6),
        "recent_observations": [observation_service.to_out(item) for item in latest_observations],
        "outstanding": {
            # Questions and goals in the notebook that are still open.
            "open_notes": [{"id": note.id, "title": note.title, "note_type": note.note_type} for note in open_notes],
            # Matches that have a video linked but not a single observation yet.
            "matches_to_analyse": list(waiting_matches),
            # Players you have recorded but never written an assessment for.
            "players_without_assessment": [{"id": player.id, "full_name": player.full_name}
                                           for player in unassessed_players],
        },
    }
