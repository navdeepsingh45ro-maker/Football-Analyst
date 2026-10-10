"""API routes for teams, competitions and seasons.

You rarely need to create these by hand: typing a new name in a player or match
form creates it. These routes exist to list them (for the suggestion lists),
fix a spelling, and remove ones that are no longer used.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from models import Competition, Season, Team
from schemas.reference_schema import CompetitionIn, CompetitionOut, SeasonIn, SeasonOut, TeamIn, TeamOut
from services import reference_service

router = APIRouter(prefix="/api", tags=["teams, competitions, seasons"])


# ── Teams ────────────────────────────────────────────────────────────────────
@router.get("/teams", response_model=list[TeamOut])
def list_teams(db: Session = Depends(get_db)):
    return db.scalars(select(Team).order_by(Team.name)).all()


@router.post("/teams", response_model=TeamOut, status_code=201)
def create_team(data: TeamIn, db: Session = Depends(get_db)):
    return reference_service.create(db, "team", data.model_dump())


@router.put("/teams/{team_id}", response_model=TeamOut)
def update_team(team_id: int, data: TeamIn, db: Session = Depends(get_db)):
    return reference_service.rename_or_update(db, "team", team_id, data.model_dump())


@router.delete("/teams/{team_id}", status_code=204)
def delete_team(team_id: int, db: Session = Depends(get_db)):
    reference_service.delete(db, "team", team_id)


# ── Competitions ─────────────────────────────────────────────────────────────
@router.get("/competitions", response_model=list[CompetitionOut])
def list_competitions(db: Session = Depends(get_db)):
    return db.scalars(select(Competition).order_by(Competition.name)).all()


@router.post("/competitions", response_model=CompetitionOut, status_code=201)
def create_competition(data: CompetitionIn, db: Session = Depends(get_db)):
    return reference_service.create(db, "competition", data.model_dump())


@router.put("/competitions/{competition_id}", response_model=CompetitionOut)
def update_competition(competition_id: int, data: CompetitionIn, db: Session = Depends(get_db)):
    return reference_service.rename_or_update(db, "competition", competition_id, data.model_dump())


@router.delete("/competitions/{competition_id}", status_code=204)
def delete_competition(competition_id: int, db: Session = Depends(get_db)):
    reference_service.delete(db, "competition", competition_id)


# ── Seasons ──────────────────────────────────────────────────────────────────
@router.get("/seasons", response_model=list[SeasonOut])
def list_seasons(db: Session = Depends(get_db)):
    return db.scalars(select(Season).order_by(Season.name.desc())).all()


@router.post("/seasons", response_model=SeasonOut, status_code=201)
def create_season(data: SeasonIn, db: Session = Depends(get_db)):
    return reference_service.create(db, "season", data.model_dump())


@router.put("/seasons/{season_id}", response_model=SeasonOut)
def update_season(season_id: int, data: SeasonIn, db: Session = Depends(get_db)):
    return reference_service.rename_or_update(db, "season", season_id, data.model_dump())


@router.delete("/seasons/{season_id}", status_code=204)
def delete_season(season_id: int, db: Session = Depends(get_db)):
    reference_service.delete(db, "season", season_id)
