"""API routes for the optional AI assistance."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from services import ai, ai_service

router = APIRouter(prefix="/api/ai", tags=["optional AI"])


class PlayerAnalysisRequest(BaseModel):
    player_id: int
    task: str = "summary"


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
