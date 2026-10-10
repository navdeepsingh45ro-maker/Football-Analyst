"""API route for the dashboard."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from schemas.common import OutputSchema, UtcDateTime
from schemas.match_schema import MatchBrief
from schemas.observation_schema import ObservationOut
from services import dashboard_service

router = APIRouter(prefix="/api", tags=["dashboard"])


class Counts(OutputSchema):
    players: int
    matches: int
    matches_analysed: int  # matches with at least one observation
    observations: int
    diagrams: int
    assessments: int
    notes: int


class RecentPlayer(OutputSchema):
    id: int
    full_name: str
    primary_position: str | None
    last_activity: UtcDateTime
    activity: str  # "observation" or "assessment"


class RecentMatch(OutputSchema):
    match: MatchBrief
    observation_count: int
    last_activity: UtcDateTime


class OpenNote(OutputSchema):
    id: int
    title: str
    note_type: str


class PlayerName(OutputSchema):
    id: int
    full_name: str


class Outstanding(OutputSchema):
    open_notes: list[OpenNote]
    matches_to_analyse: list[MatchBrief]
    players_without_assessment: list[PlayerName]


class Dashboard(OutputSchema):
    counts: Counts
    recent_players: list[RecentPlayer]
    recent_matches: list[RecentMatch]
    recent_observations: list[ObservationOut]
    outstanding: Outstanding


@router.get("/dashboard", response_model=Dashboard)
def dashboard(db: Session = Depends(get_db)):
    return dashboard_service.summary(db)
