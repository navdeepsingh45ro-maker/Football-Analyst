"""The coaching notebook: notes on what you learn, and training ideas that follow from them.

The point of this module is the TRAIL. A note or a training idea remembers which
observations it was written because of, and a training idea remembers which note
it grew out of:

    observation  ->  coaching note  ->  training idea

so months later the reasoning can still be followed back to what you actually saw.
"""
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from errors import NotFound
from models import CoachingNote, Match, Observation, Player, TrainingIdea
from models.notebook_model import coaching_note_observations, training_idea_observations
from schemas.notebook_schema import CoachingNoteIn, TrainingIdeaIn
from services.common import get_or_404, like_pattern


def _observations(db: Session, observation_ids: list[int]) -> list[Observation]:
    """Load the observations to link, in the order given. Every id must exist."""
    if not observation_ids:
        return []
    found = {observation.id: observation
             for observation in db.scalars(select(Observation).where(Observation.id.in_(observation_ids)))}
    missing = [observation_id for observation_id in observation_ids if observation_id not in found]
    if missing:
        raise NotFound(f"Observation {missing[0]} does not exist")
    return [found[observation_id] for observation_id in observation_ids]


# ── Coaching notes ───────────────────────────────────────────────────────────
def _apply_note(db: Session, note: CoachingNote, data: CoachingNoteIn) -> None:
    if data.player_id is not None:
        get_or_404(db, Player, data.player_id, "Player")
    if data.match_id is not None:
        get_or_404(db, Match, data.match_id, "Match")
    for field in ("note_type", "title", "body", "tags", "status", "player_id", "match_id"):
        setattr(note, field, getattr(data, field))
    note.observations = _observations(db, data.observation_ids)


def create_note(db: Session, data: CoachingNoteIn) -> CoachingNote:
    note = CoachingNote()
    db.add(note)
    _apply_note(db, note, data)
    db.commit()
    return note


def update_note(db: Session, note_id: int, data: CoachingNoteIn) -> CoachingNote:
    note = get_or_404(db, CoachingNote, note_id, "Coaching note")
    _apply_note(db, note, data)
    db.commit()
    return note


def delete_note(db: Session, note_id: int) -> None:
    """Delete a note. Training ideas that grew out of it are kept (they just lose the link)."""
    db.delete(get_or_404(db, CoachingNote, note_id, "Coaching note"))
    db.commit()


def list_notes(db: Session, note_type: str | None = None, status: str | None = None, q: str | None = None,
               player_id: int | None = None, observation_id: int | None = None) -> list[CoachingNote]:
    """Notes, newest first. `status="open"` gives the questions and goals still waiting."""
    statement = select(CoachingNote).order_by(CoachingNote.updated_at.desc(), CoachingNote.id.desc())
    if note_type:
        statement = statement.where(CoachingNote.note_type == note_type)
    if status:
        statement = statement.where(CoachingNote.status == status)
    if player_id is not None:
        statement = statement.where(CoachingNote.player_id == player_id)
    if observation_id is not None:
        statement = statement.where(CoachingNote.id.in_(
            select(coaching_note_observations.c.coaching_note_id)
            .where(coaching_note_observations.c.observation_id == observation_id)))
    if q and q.strip():
        pattern = like_pattern(q.strip())
        statement = statement.where(or_(CoachingNote.title.like(pattern, escape="\\"),
                                        CoachingNote.body.like(pattern, escape="\\")))
    return list(db.scalars(statement))


# ── Training ideas ───────────────────────────────────────────────────────────
def _apply_idea(db: Session, idea: TrainingIdea, data: TrainingIdeaIn) -> None:
    if data.source_note_id is not None:
        get_or_404(db, CoachingNote, data.source_note_id, "Coaching note")
    for field in ("title", "objective", "setup", "instructions", "coaching_points", "duration_minutes",
                  "players_needed", "source_note_id"):
        setattr(idea, field, getattr(data, field))
    idea.observations = _observations(db, data.observation_ids)


def create_idea(db: Session, data: TrainingIdeaIn) -> TrainingIdea:
    idea = TrainingIdea()
    db.add(idea)
    _apply_idea(db, idea, data)
    db.commit()
    return idea


def update_idea(db: Session, idea_id: int, data: TrainingIdeaIn) -> TrainingIdea:
    idea = get_or_404(db, TrainingIdea, idea_id, "Training idea")
    _apply_idea(db, idea, data)
    db.commit()
    return idea


def delete_idea(db: Session, idea_id: int) -> None:
    db.delete(get_or_404(db, TrainingIdea, idea_id, "Training idea"))
    db.commit()


def list_ideas(db: Session, q: str | None = None, observation_id: int | None = None) -> list[TrainingIdea]:
    statement = select(TrainingIdea).order_by(TrainingIdea.updated_at.desc(), TrainingIdea.id.desc())
    if observation_id is not None:
        statement = statement.where(TrainingIdea.id.in_(
            select(training_idea_observations.c.training_idea_id)
            .where(training_idea_observations.c.observation_id == observation_id)))
    if q and q.strip():
        pattern = like_pattern(q.strip())
        statement = statement.where(or_(*[getattr(TrainingIdea, field).like(pattern, escape="\\")
                                          for field in ("title", "objective", "setup", "instructions",
                                                        "coaching_points")]))
    return list(db.scalars(statement))
