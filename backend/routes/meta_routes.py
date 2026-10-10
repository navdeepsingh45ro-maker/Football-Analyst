"""Facts about the app itself: is it healthy, and which choices does it offer."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

import config
import vocabulary
from database import get_db
from migrations_runner import current_revision, head_revision
from models import ASSESSMENT_SECTIONS, STAT_FIELDS

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    """Confirms the server can reach the database and that its tables are up to date."""
    db.execute(text("SELECT 1"))
    revision = current_revision()
    return {
        "status": "ok",
        "database": "ok",
        "schema_revision": revision,
        "schema_is_current": revision == head_revision(),
    }


@router.get("/meta/vocabulary")
def vocabulary_lists():
    """Every suggestion list and fixed choice, so the frontend never hard-codes them."""
    return {
        "positions": vocabulary.POSITIONS,
        "position_groups": vocabulary.POSITION_GROUPS,
        "preferred_feet": vocabulary.PREFERRED_FEET,
        "rating_attributes": vocabulary.RATING_ATTRIBUTES,
        "rating_scale": {str(value): label for value, label in vocabulary.RATING_SCALE.items()},
        "rating_scale_note": vocabulary.RATING_SCALE_NOTE,
        "assessment_sections": ASSESSMENT_SECTIONS,
        "stat_fields": STAT_FIELDS,
        "observation_categories": vocabulary.OBSERVATION_CATEGORIES,
        "movement_categories": vocabulary.MOVEMENT_CATEGORIES,
        "outcomes": vocabulary.OUTCOMES,
        "shot_or_chance_outcomes": vocabulary.SHOT_OR_CHANCE_OUTCOMES,
        "confidence_levels": vocabulary.CONFIDENCE_LEVELS,
        "zone_types": vocabulary.ZONE_TYPES,
        "annotation_kinds": {kind: {"min_points": low, "max_points": high}
                             for kind, (low, high) in vocabulary.ANNOTATION_KINDS.items()},
        "pitch": {
            "length_m": vocabulary.PITCH_LENGTH_M,
            "width_m": vocabulary.PITCH_WIDTH_M,
            "margin_m": vocabulary.PITCH_MARGIN_M,
        },
        "video_kinds": vocabulary.VIDEO_KINDS,
        "video_extensions": sorted(config.VIDEO_EXTENSIONS),
        "note_types": vocabulary.NOTE_TYPES,
        "note_statuses": vocabulary.NOTE_STATUSES,
    }
