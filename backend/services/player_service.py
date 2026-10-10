"""Players: creating, editing, listing, and the history shown on a profile."""
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from errors import Conflict
from models import (
    CoachingNote, MatchAppearance, Observation, ObservationPlayer, Player, PlayerStatistic,
    ScoutingAssessment, TacticalSnapshot,
)
from schemas.player_schema import PlayerIn
from services import reference_service
from services.common import get_or_404, like_pattern


def find_same_person(db: Session, full_name: str, date_of_birth: date | None,
                     exclude_id: int | None = None) -> Player | None:
    """Another player with the same name and the same birth date (or both birth dates unknown)."""
    statement = select(Player).where(Player.full_name == full_name)  # NOCASE: ignores upper/lower case
    if date_of_birth is None:
        statement = statement.where(Player.date_of_birth.is_(None))
    else:
        statement = statement.where(Player.date_of_birth == date_of_birth)
    if exclude_id is not None:
        statement = statement.where(Player.id != exclude_id)
    return db.scalars(statement).first()


def _refuse_duplicates(db: Session, data: PlayerIn, allow_duplicate: bool, exclude_id: int | None = None) -> None:
    twin = find_same_person(db, data.full_name, data.date_of_birth, exclude_id)
    if twin is None:
        return
    if data.date_of_birth is not None:
        # Same name and same birth date: certainly the same person.
        raise Conflict(
            f"{twin.full_name}, born {data.date_of_birth.isoformat()}, is already recorded (player #{twin.id}).",
            existing_player_id=twin.id, can_override=False,
        )
    if not allow_duplicate:
        # Same name, no birth dates: possibly two people. Ask instead of guessing.
        raise Conflict(
            f"A player called {twin.full_name} is already recorded (player #{twin.id}) and neither has a date of "
            "birth, so they may be the same person. Add a date of birth, or confirm that this is a different player.",
            existing_player_id=twin.id, can_override=True,
        )


def _apply(db: Session, player: Player, data: PlayerIn) -> None:
    for field, value in data.model_dump(exclude={"current_team", "national_team"}).items():
        setattr(player, field, value)
    player.current_team = reference_service.get_or_create_team(db, data.current_team)
    player.national_team = reference_service.get_or_create_team(db, data.national_team, team_type="national")


def create_player(db: Session, data: PlayerIn, allow_duplicate: bool = False, commit: bool = True) -> Player:
    """Add a player. With commit=False the caller decides when to commit (the CSV import
    adds many rows and commits once, so a bad row can cancel the whole file)."""
    _refuse_duplicates(db, data, allow_duplicate)
    player = Player()
    _apply(db, player, data)
    db.add(player)
    if commit:
        db.commit()
    else:
        db.flush()
    return player


def update_player(db: Session, player_id: int, data: PlayerIn, allow_duplicate: bool = False) -> Player:
    """Replace a player's biography. Observations and assessments are separate rows and are untouched."""
    player = get_or_404(db, Player, player_id, "Player")
    _refuse_duplicates(db, data, allow_duplicate, exclude_id=player_id)
    _apply(db, player, data)
    db.commit()
    return player


def list_players(db: Session, q: str | None = None, team_id: int | None = None,
                 position: str | None = None) -> list[tuple[Player, int, date | None]]:
    """Players by name, each with their observation count and the date of their latest assessment."""
    statement = select(Player).order_by(Player.full_name)
    if q:
        pattern = like_pattern(q)
        statement = statement.where(or_(Player.full_name.like(pattern, escape="\\"),
                                        Player.nationality.like(pattern, escape="\\")))
    if team_id is not None:
        statement = statement.where(Player.current_team_id == team_id)
    if position:
        statement = statement.where(Player.primary_position == position)
    players = db.scalars(statement).all()

    # Two grouped queries instead of two queries per player.
    observation_counts = dict(db.execute(
        select(ObservationPlayer.player_id, func.count()).group_by(ObservationPlayer.player_id)).all())
    latest_assessments = dict(db.execute(
        select(ScoutingAssessment.player_id, func.max(ScoutingAssessment.assessed_on))
        .group_by(ScoutingAssessment.player_id)).all())
    return [(player, observation_counts.get(player.id, 0), latest_assessments.get(player.id)) for player in players]


def player_counts(db: Session, player_id: int) -> dict[str, int]:
    """How much is recorded about a player (for the numbers on the profile tabs)."""
    def count(model, column) -> int:
        return db.scalar(select(func.count()).select_from(model).where(column == player_id)) or 0

    diagrams = db.scalar(
        select(func.count(func.distinct(TacticalSnapshot.id)))
        .join(Observation, TacticalSnapshot.observation_id == Observation.id)
        .join(ObservationPlayer, ObservationPlayer.observation_id == Observation.id)
        .where(ObservationPlayer.player_id == player_id)
    ) or 0
    return {
        "observations": count(ObservationPlayer, ObservationPlayer.player_id),
        "assessments": count(ScoutingAssessment, ScoutingAssessment.player_id),
        "appearances": count(MatchAppearance, MatchAppearance.player_id),
        "statistics": count(PlayerStatistic, PlayerStatistic.player_id),
        "diagrams": diagrams,
        "notes": count(CoachingNote, CoachingNote.player_id),
    }


def player_timeline(db: Session, player_id: int) -> list[dict]:
    """Everything recorded about a player in date order, newest first.

    An event's date is when it HAPPENED (the match date, the assessment date),
    not when you typed it in. Events from a match with no known date come last.
    """
    get_or_404(db, Player, player_id, "Player")
    events: list[dict] = []

    for assessment in db.scalars(select(ScoutingAssessment).where(ScoutingAssessment.player_id == player_id)):
        events.append({"kind": "assessment", "date": assessment.assessed_on, "title": "Scouting assessment",
                       "detail": assessment.summary or assessment.basis, "record_id": assessment.id})

    observations = db.scalars(select(Observation).join(ObservationPlayer)
                              .where(ObservationPlayer.player_id == player_id))
    for observation in observations:
        match = observation.match
        title = observation.category
        if observation.movement_category:
            title += f": {observation.movement_category}"
        if match is not None:
            title += f" ({match.title})"
        events.append({
            "kind": "observation",
            "date": match.match_date if match is not None else observation.created_at.date(),
            "title": title, "detail": observation.notes or observation.tactical_situation,
            "record_id": observation.id, "match_id": observation.match_id,
        })

    for appearance in db.scalars(select(MatchAppearance).where(MatchAppearance.player_id == player_id)):
        role = "Started" if appearance.is_starter else "Substitute"
        if appearance.minute_on is not None:
            role += f", on at {appearance.minute_on}'"
        if appearance.minute_off is not None:
            role += f", off at {appearance.minute_off}'"
        events.append({"kind": "appearance", "date": appearance.match.match_date,
                       "title": f"Played in {appearance.match.title}", "detail": role,
                       "record_id": appearance.id, "match_id": appearance.match_id})

    for note in db.scalars(select(CoachingNote).where(CoachingNote.player_id == player_id)):
        events.append({"kind": "note", "date": note.created_at.date(), "title": note.title,
                       "detail": note.note_type, "record_id": note.id})

    events.sort(key=lambda event: (event["date"] is None, -(event["date"].toordinal() if event["date"] else 0)))
    return events
