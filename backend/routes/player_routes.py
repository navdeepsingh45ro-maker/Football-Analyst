"""API routes for players, their scouting assessments and their statistics.

Routes stay thin on purpose: they read the request, call a service, and shape
the answer. The rules live in services/.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import Player
from schemas.assessment_schema import AssessmentIn, AssessmentOut, RatingHistory
from schemas.player_schema import PlayerDetail, PlayerIn, PlayerListItem, PlayerOut, TimelineEvent
from schemas.statistic_schema import StatisticIn, StatisticOut
from services import assessment_service, deletion_service, player_service, statistic_service
from services.common import get_or_404

router = APIRouter(prefix="/api", tags=["players"])


# ── Players ──────────────────────────────────────────────────────────────────
@router.get("/players", response_model=list[PlayerListItem])
def list_players(q: str | None = None, team_id: int | None = None, position: str | None = None,
                 db: Session = Depends(get_db)):
    rows = player_service.list_players(db, q=q, team_id=team_id, position=position)
    return [
        {**PlayerOut.model_validate(player).model_dump(),
         "observation_count": observation_count, "latest_assessment_on": latest_assessment_on}
        for player, observation_count, latest_assessment_on in rows
    ]


@router.post("/players", response_model=PlayerOut, status_code=201)
def create_player(data: PlayerIn, allow_duplicate: bool = False, db: Session = Depends(get_db)):
    return player_service.create_player(db, data, allow_duplicate=allow_duplicate)


@router.get("/players/{player_id}", response_model=PlayerDetail)
def get_player(player_id: int, db: Session = Depends(get_db)):
    player = get_or_404(db, Player, player_id, "Player")
    return {**PlayerOut.model_validate(player).model_dump(), "counts": player_service.player_counts(db, player_id)}


@router.put("/players/{player_id}", response_model=PlayerOut)
def update_player(player_id: int, data: PlayerIn, allow_duplicate: bool = False, db: Session = Depends(get_db)):
    return player_service.update_player(db, player_id, data, allow_duplicate=allow_duplicate)


@router.get("/players/{player_id}/dependencies")
def player_dependencies(player_id: int, db: Session = Depends(get_db)):
    """What is attached to a player. The interface shows this before asking to confirm a delete."""
    get_or_404(db, Player, player_id, "Player")
    return deletion_service.player_dependencies(db, player_id)


@router.delete("/players/{player_id}", status_code=204)
def delete_player(player_id: int, cascade: bool = False, db: Session = Depends(get_db)):
    deletion_service.delete_player(db, player_id, cascade=cascade)


@router.get("/players/{player_id}/timeline", response_model=list[TimelineEvent])
def player_timeline(player_id: int, db: Session = Depends(get_db)):
    return player_service.player_timeline(db, player_id)


# ── Scouting assessments ─────────────────────────────────────────────────────
@router.get("/players/{player_id}/assessments", response_model=list[AssessmentOut])
def list_assessments(player_id: int, db: Session = Depends(get_db)):
    return assessment_service.list_assessments(db, player_id)


@router.post("/players/{player_id}/assessments", response_model=AssessmentOut, status_code=201)
def create_assessment(player_id: int, data: AssessmentIn, db: Session = Depends(get_db)):
    return assessment_service.create_assessment(db, player_id, data)


@router.get("/players/{player_id}/rating-history", response_model=RatingHistory)
def rating_history(player_id: int, db: Session = Depends(get_db)):
    return assessment_service.rating_history(db, player_id)


@router.put("/assessments/{assessment_id}", response_model=AssessmentOut)
def update_assessment(assessment_id: int, data: AssessmentIn, db: Session = Depends(get_db)):
    return assessment_service.update_assessment(db, assessment_id, data)


@router.delete("/assessments/{assessment_id}", status_code=204)
def delete_assessment(assessment_id: int, db: Session = Depends(get_db)):
    assessment_service.delete_assessment(db, assessment_id)


# ── Statistics ───────────────────────────────────────────────────────────────
@router.get("/players/{player_id}/statistics", response_model=list[StatisticOut])
def list_statistics(player_id: int, db: Session = Depends(get_db)):
    return statistic_service.list_statistics(db, player_id)


@router.post("/players/{player_id}/statistics", response_model=StatisticOut, status_code=201)
def create_statistic(player_id: int, data: StatisticIn, db: Session = Depends(get_db)):
    return statistic_service.create_statistic(db, player_id, data)


@router.put("/statistics/{statistic_id}", response_model=StatisticOut)
def update_statistic(statistic_id: int, data: StatisticIn, db: Session = Depends(get_db)):
    return statistic_service.update_statistic(db, statistic_id, data)


@router.delete("/statistics/{statistic_id}", status_code=204)
def delete_statistic(statistic_id: int, db: Session = Depends(get_db)):
    statistic_service.delete_statistic(db, statistic_id)
