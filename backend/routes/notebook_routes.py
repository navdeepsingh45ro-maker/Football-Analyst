"""API routes for the coaching notebook."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import CoachingNote, TrainingIdea
from schemas.notebook_schema import CoachingNoteIn, CoachingNoteOut, TrainingIdeaIn, TrainingIdeaOut
from services import notebook_service
from services.common import get_or_404

router = APIRouter(prefix="/api", tags=["notebook"])


# ── Coaching notes ───────────────────────────────────────────────────────────
@router.get("/notes", response_model=list[CoachingNoteOut])
def list_notes(note_type: str | None = None, status: str | None = None, q: str | None = None,
               player_id: int | None = None, observation_id: int | None = None, db: Session = Depends(get_db)):
    return notebook_service.list_notes(db, note_type=note_type, status=status, q=q, player_id=player_id,
                                       observation_id=observation_id)


@router.post("/notes", response_model=CoachingNoteOut, status_code=201)
def create_note(data: CoachingNoteIn, db: Session = Depends(get_db)):
    return notebook_service.create_note(db, data)


@router.get("/notes/{note_id}", response_model=CoachingNoteOut)
def get_note(note_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, CoachingNote, note_id, "Coaching note")


@router.put("/notes/{note_id}", response_model=CoachingNoteOut)
def update_note(note_id: int, data: CoachingNoteIn, db: Session = Depends(get_db)):
    return notebook_service.update_note(db, note_id, data)


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: int, db: Session = Depends(get_db)):
    notebook_service.delete_note(db, note_id)


# ── Training ideas ───────────────────────────────────────────────────────────
@router.get("/training-ideas", response_model=list[TrainingIdeaOut])
def list_ideas(q: str | None = None, observation_id: int | None = None, db: Session = Depends(get_db)):
    return notebook_service.list_ideas(db, q=q, observation_id=observation_id)


@router.post("/training-ideas", response_model=TrainingIdeaOut, status_code=201)
def create_idea(data: TrainingIdeaIn, db: Session = Depends(get_db)):
    return notebook_service.create_idea(db, data)


@router.get("/training-ideas/{idea_id}", response_model=TrainingIdeaOut)
def get_idea(idea_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, TrainingIdea, idea_id, "Training idea")


@router.put("/training-ideas/{idea_id}", response_model=TrainingIdeaOut)
def update_idea(idea_id: int, data: TrainingIdeaIn, db: Session = Depends(get_db)):
    return notebook_service.update_idea(db, idea_id, data)


@router.delete("/training-ideas/{idea_id}", status_code=204)
def delete_idea(idea_id: int, db: Session = Depends(get_db)):
    notebook_service.delete_idea(db, idea_id)
