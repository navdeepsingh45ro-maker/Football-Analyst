"""API routes for the optional AI assistance."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from services import ai, ai_service

router = APIRouter(prefix="/api/ai", tags=["optional AI"])


class PlayerAnalysisRequest(BaseModel):
    player_id: int
    task: str = "summary"


class CoachTurn(BaseModel):
    question: str
    answer: str


class CoachRequest(BaseModel):
    question: str
    player_id: int | None = None  # ask about one player...
    match_id: int | None = None  # ...and/or one match. Neither means the whole database.
    history: list[CoachTurn] = Field(default=[], max_length=50)  # earlier turns, kept by the page, not the server


@router.get("/status")
def status():
    """Is AI switched on? Never returns a key or any other secret."""
    return {**ai.status(), "tasks": {key: name for key, (name, _) in ai_service.TASKS.items()}}


@router.post("/player-analysis")
def player_analysis(request: PlayerAnalysisRequest, db: Session = Depends(get_db)):
    """Ask the AI about one player, using only that player's stored records.

    Answers 503 with an explanation when AI is off or not set up. Nothing is
    saved: the result is returned for you to read and, if you wish, keep.
    """
    return ai_service.analyse_player(db, request.player_id, request.task)


@router.post("/coach")
def coach(request: CoachRequest, db: Session = Depends(get_db)):
    """Ask the AI coach a question of your own, about a player, a match, everything, or coaching in general.

    What it says about your players is checked against your stored records;
    general coaching advice is marked as such. Nothing is saved.
    """
    return ai_service.ask_coach(db, request.question, request.player_id, request.match_id,
                                [turn.model_dump() for turn in request.history])
