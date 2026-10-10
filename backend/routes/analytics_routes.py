"""API routes for the pattern reports and player comparisons.

Every route takes the same filters as the observation search (same code, see
ObservationFilters), so a report always counts exactly the observations that
the Observations page would list for those filters.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from errors import Invalid
from services import analytics_service
from services.observation_service import ObservationFilters

router = APIRouter(prefix="/api/analytics", tags=["reports"])


@router.get("/dimensions")
def dimensions():
    """The things observations can be grouped by: { name: heading }."""
    return {name: heading for name, (heading, _) in analytics_service.DIMENSIONS.items()}


@router.get("/patterns")
def patterns(group_by: str = "movement_category", filters: ObservationFilters = Depends(),
             db: Session = Depends(get_db)):
    """How many matching observations fall into each value of `group_by`, with their ids."""
    return analytics_service.patterns(db, filters, group_by)


@router.get("/crosstab")
def crosstab(rows: str = "movement_category", columns: str = "outcome",
             filters: ObservationFilters = Depends(), db: Session = Depends(get_db)):
    """Counts for every combination of two groupings, e.g. each movement against each outcome."""
    return analytics_service.crosstab(db, filters, rows, columns)


@router.get("/zones")
def zones(point: str = "start", filters: ObservationFilters = Depends(), db: Session = Depends(get_db)):
    """Where recorded movements started (or ended) on a 3 x 5 grid of the pitch."""
    return analytics_service.zone_grid(db, filters, point)


@router.get("/compare-players")
def compare_players(player_ids: str, basis: str = "season", season_id: int | None = None,
                    competition_id: int | None = None, db: Session = Depends(get_db)):
    """Recorded numbers of two or more players side by side, with the limits of the comparison."""
    try:
        ids = [int(part) for part in player_ids.split(",") if part.strip()]
    except ValueError:
        raise Invalid("player_ids must be numbers separated by commas, for example 1,4") from None
    return analytics_service.compare_players(db, ids, basis, season_id, competition_id)
