"""API routes for observations and tactical snapshots (diagrams)."""
from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db
from models import Observation, TacticalSnapshot
from schemas.observation_schema import (
    ObservationCreate, ObservationDetail, ObservationIn, ObservationPage, SnapshotIn, SnapshotOut, SnapshotSummary,
)
from services import deletion_service, observation_service, snapshot_service
from services.common import get_or_404
from services.observation_service import ObservationFilters

router = APIRouter(prefix="/api", tags=["observations"])


# ── Observations ─────────────────────────────────────────────────────────────
@router.get("/observations", response_model=ObservationPage)
def list_observations(filters: ObservationFilters = Depends(), limit: int = Query(100, ge=1, le=500),
                      offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    """Search observations. Every filter is optional and they combine with AND."""
    total, items = observation_service.search(db, filters, limit=limit, offset=offset)
    return {"total": total, "items": [observation_service.to_out(item) for item in items]}


@router.post("/observations", response_model=ObservationDetail, status_code=201)
def create_observation(data: ObservationCreate, db: Session = Depends(get_db)):
    """Save an observation, optionally together with the diagram drawn for it."""
    return observation_service.to_detail(observation_service.create_observation(db, data))


@router.get("/observations/{observation_id}", response_model=ObservationDetail)
def get_observation(observation_id: int, db: Session = Depends(get_db)):
    return observation_service.to_detail(get_or_404(db, Observation, observation_id, "Observation"))


@router.put("/observations/{observation_id}", response_model=ObservationDetail)
def update_observation(observation_id: int, data: ObservationIn, db: Session = Depends(get_db)):
    return observation_service.to_detail(observation_service.update_observation(db, observation_id, data))


@router.delete("/observations/{observation_id}", status_code=204)
def delete_observation(observation_id: int, db: Session = Depends(get_db)):
    deletion_service.delete_observation(db, observation_id)


@router.post("/observations/{observation_id}/snapshots", response_model=SnapshotOut, status_code=201)
def add_snapshot_to_observation(observation_id: int, data: SnapshotIn, db: Session = Depends(get_db)):
    """Add a further diagram to an observation that already exists."""
    return snapshot_service.to_out(snapshot_service.create_snapshot(db, data, observation_id=observation_id))


# ── Diagrams ─────────────────────────────────────────────────────────────────
@router.get("/snapshots", response_model=list[SnapshotSummary])
def list_standalone_snapshots(db: Session = Depends(get_db)):
    """Diagrams made on the Tactical Pitch page that are not tied to an observation."""
    return [snapshot_service.to_summary(snapshot) for snapshot in snapshot_service.list_standalone(db)]


@router.post("/snapshots", response_model=SnapshotOut, status_code=201)
def create_standalone_snapshot(data: SnapshotIn, db: Session = Depends(get_db)):
    return snapshot_service.to_out(snapshot_service.create_snapshot(db, data))


@router.get("/snapshots/{snapshot_id}", response_model=SnapshotOut)
def get_snapshot(snapshot_id: int, db: Session = Depends(get_db)):
    return snapshot_service.to_out(get_or_404(db, TacticalSnapshot, snapshot_id, "Diagram"))


@router.put("/snapshots/{snapshot_id}", response_model=SnapshotOut)
def update_snapshot(snapshot_id: int, data: SnapshotIn, db: Session = Depends(get_db)):
    """Replace a diagram's shapes (and optionally its picture) with what the editor sends."""
    return snapshot_service.to_out(snapshot_service.update_snapshot(db, snapshot_id, data))


@router.delete("/snapshots/{snapshot_id}", status_code=204)
def delete_snapshot(snapshot_id: int, db: Session = Depends(get_db)):
    deletion_service.delete_snapshot(db, snapshot_id)


@router.get("/snapshots/{snapshot_id}/frame")
def snapshot_frame(snapshot_id: int, db: Session = Depends(get_db)):
    """The saved frame picture of a diagram."""
    path, media_type = snapshot_service.frame_file(get_or_404(db, TacticalSnapshot, snapshot_id, "Diagram"))
    # Safe to cache for a long time: a replaced picture gets a different address (see frame_image_url).
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=31536000"})


@router.get("/players/{player_id}/diagrams", response_model=list[SnapshotSummary])
def player_diagrams(player_id: int, db: Session = Depends(get_db)):
    """Every diagram drawn for an observation involving this player."""
    return [snapshot_service.to_summary(snapshot) for snapshot in snapshot_service.list_for_player(db, player_id)]
