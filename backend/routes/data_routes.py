"""API routes for exporting, importing and backing up your data."""
import json
from datetime import date

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import config
from database import get_db
from errors import Invalid
from migrations_runner import current_revision
from models import Observation, Player, TacticalSnapshot
from services import backup_service, transfer_service
from services.observation_service import ObservationFilters

router = APIRouter(prefix="/api", tags=["your data"])

MAX_IMPORT_BYTES = 10 * 1024 * 1024


def _download(content: str, file_name: str, media_type: str) -> Response:
    return Response(content=content, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{file_name}"'})


# ── Export ───────────────────────────────────────────────────────────────────
@router.get("/export/json")
def export_json(db: Session = Depends(get_db)):
    """Everything in one file: every table with its ids and links."""
    content = json.dumps(transfer_service.export_all(db), indent=1, ensure_ascii=False)
    return _download(content, f"football-analyst-export-{date.today().isoformat()}.json", "application/json")


@router.get("/export/csv/{entity}")
def export_csv(entity: str, filters: ObservationFilters = Depends(), db: Session = Depends(get_db)):
    """One kind of record as a spreadsheet file. For observations the usual filters apply."""
    content = transfer_service.export_csv(db, entity, filters)
    return _download(content, f"football-analyst-{entity}-{date.today().isoformat()}.csv", "text/csv; charset=utf-8")


# ── Import ───────────────────────────────────────────────────────────────────
@router.post("/import/csv/{entity}")
async def import_csv(entity: str, request: Request, dry_run: bool = False, db: Session = Depends(get_db)):
    """Add the rows of a CSV file (sent as the request body). All rows or none; dry_run only checks."""
    raw = await request.body()
    if len(raw) > MAX_IMPORT_BYTES:
        raise Invalid("The file is larger than 10 MB. Split it into smaller files.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Invalid("The file is not UTF-8 text. In your spreadsheet, export it as 'CSV UTF-8'.") from None
    return transfer_service.import_csv(db, entity, text, dry_run=dry_run)


@router.post("/import/json")
def import_json(payload: dict = Body(...), dry_run: bool = False, db: Session = Depends(get_db)):
    """Load a JSON export into an empty database. Never overwrites existing data."""
    return transfer_service.import_all(db, payload, dry_run=dry_run)


# ── Backups ──────────────────────────────────────────────────────────────────
@router.get("/backups")
def list_backups():
    return backup_service.list_backups()


@router.post("/backups", status_code=201)
def create_backup():
    """Make a backup archive now, and check it can be read back."""
    return backup_service.create_backup()


@router.get("/backups/{name}")
def download_backup(name: str):
    return FileResponse(backup_service.backup_path(name), media_type="application/zip", filename=name)


@router.get("/about")
def about(db: Session = Depends(get_db)):
    """Where your data lives on this computer, for the Settings page."""
    def count(model) -> int:
        return db.scalar(select(func.count()).select_from(model)) or 0

    return {
        "data_folder": str(config.DATA_DIR),
        "database_file": str(config.DATABASE_FILE),
        "frames_folder": str(config.FRAMES_DIR),
        "backups_folder": str(config.BACKUPS_DIR),
        "schema_revision": current_revision(),
        "players": count(Player),
        "observations": count(Observation),
        "diagrams": count(TacticalSnapshot),
        "frame_pictures": len([path for path in config.FRAMES_DIR.glob("*") if path.is_file()]),
    }
