"""API routes for looking a player up on the web (Wikidata). Nothing here saves anything."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from services import lookup_service

router = APIRouter(prefix="/api/lookup", tags=["web lookup"])


@router.get("/players")
def search_players(q: str = ""):
    """Football players on Wikidata whose name matches `q`. Sends that name to Wikidata and nothing else."""
    return lookup_service.search_players(q)


@router.get("/players/{wikidata_id}")
def player_details(wikidata_id: str, db: Session = Depends(get_db)):
    """What Wikidata states about one player, shaped as values for the player form, with notes on what was left out.

    The database is only read (to recognise a club you already have under a
    slightly different name). Answers 503 with an explanation when Wikidata
    cannot be reached.
    """
    return lookup_service.player_details(db, wikidata_id)
