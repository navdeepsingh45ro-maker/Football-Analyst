"""Tactical snapshots: saving a diagram, its shapes and its frame picture as ONE unit.

A diagram is spread over three places: a row in tactical_snapshots, many rows in
annotations, and (sometimes) a picture file in data/media/frames. `saving_files`
below is what keeps the three in step:

    with saving_files(db) as files:
        ... change rows, write pictures (recording them in `files`) ...

    success  -> everything is committed, then pictures that were replaced are removed
    failure  -> the database change is rolled back AND any picture written during
                the attempt is deleted, so no half-saved diagram is left behind
"""
import base64
import binascii
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

import config
from errors import Invalid, NotFound
from models import Annotation, Observation, ObservationPlayer, Player, TacticalSnapshot
from models.common import utcnow
from schemas.observation_schema import AnnotationOut, SnapshotIn
from services.common import get_or_404
from services.deletion_service import remove_frame_files

_FRAME_MEDIA_TYPES = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


@dataclass
class FileChanges:
    new: list[str] = field(default_factory=list)  # pictures written during this change
    replaced: list[str] = field(default_factory=list)  # pictures no longer needed if it succeeds


@contextmanager
def saving_files(db: Session):
    """Commit a change that may write frame pictures, cleaning up correctly either way."""
    files = FileChanges()
    try:
        yield files
        db.commit()
    except Exception:
        db.rollback()
        remove_frame_files(files.new)
        raise
    remove_frame_files(files.replaced)


def decode_frame_image(data_url: str) -> tuple[bytes, str]:
    """Turn a "data:image/...;base64,..." text into (bytes, file extension).

    The type is decided from the first bytes of the picture itself, never from
    what the sender claims it is.
    """
    header, comma, payload = data_url.partition(",")
    if not header.startswith("data:image/") or not header.endswith(";base64") or not comma:
        raise Invalid("The frame picture must be an image sent as a base64 data URL.")
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise Invalid("The frame picture is not valid base64 data.") from None
    if len(raw) > config.MAX_FRAME_BYTES:
        raise Invalid(f"The frame picture is larger than {config.MAX_FRAME_BYTES // (1024 * 1024)} MB.")
    if raw.startswith(b"\xff\xd8\xff"):
        return raw, ".jpg"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return raw, ".png"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return raw, ".webp"
    raise Invalid("The frame picture must be a JPEG, PNG or WebP image.")


def _store_frame(raw: bytes, extension: str) -> str:
    """Write a picture into the frames folder under a new random name; return that name."""
    config.FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    file_name = f"{uuid.uuid4().hex}{extension}"
    (config.FRAMES_DIR / file_name).write_bytes(raw)
    return file_name


def _check_marker_players_exist(db: Session, data: SnapshotIn) -> None:
    wanted = {annotation.player_id for annotation in data.annotations if annotation.player_id is not None}
    if not wanted:
        return
    found = set(db.scalars(select(Player.id).where(Player.id.in_(wanted))))
    if wanted - found:
        raise Invalid(f"A marker refers to player {sorted(wanted - found)[0]}, who does not exist.")


def apply(db: Session, snapshot: TacticalSnapshot, data: SnapshotIn, files: FileChanges) -> None:
    """Copy the editor's diagram into `snapshot`. Must run inside `saving_files`."""
    _check_marker_players_exist(db, data)
    snapshot.title, snapshot.notes = data.title, data.notes
    snapshot.pitch_length_m, snapshot.pitch_width_m = data.pitch_length_m, data.pitch_width_m
    snapshot.frame_width, snapshot.frame_height = data.frame_width, data.frame_height

    previous_picture = snapshot.frame_image_path
    if data.frame_image:
        raw, extension = decode_frame_image(data.frame_image)
        snapshot.frame_image_path = _store_frame(raw, extension)
        snapshot.frame_source = data.frame_source or "upload"
        files.new.append(snapshot.frame_image_path)
        if previous_picture:
            files.replaced.append(previous_picture)
    elif previous_picture and not data.keep_frame_image:
        snapshot.frame_image_path, snapshot.frame_source = None, None
        files.replaced.append(previous_picture)
    if snapshot.frame_image_path and snapshot.frame_width is None:
        raise Invalid("A diagram with a frame picture needs the frame's width and height.")

    # Replace the shapes. The old rows must be deleted before the new ones are
    # inserted, or a shape that kept its uid would briefly exist twice and break
    # the one-uid-per-diagram rule. Hence clear + flush first.
    if snapshot.annotations:
        snapshot.annotations.clear()
        db.flush()
    snapshot.annotations = [
        Annotation(uid=shape.uid, layer=shape.layer, kind=shape.kind,
                   points=[[x, y] for x, y in shape.points], label=shape.label,
                   player_id=shape.player_id, properties=shape.properties, z_index=order)
        for order, shape in enumerate(data.annotations)
    ]
    snapshot.updated_at = utcnow()  # the shapes are other rows, so say explicitly that the diagram changed


def create_snapshot(db: Session, data: SnapshotIn, observation_id: int | None = None) -> TacticalSnapshot:
    """Save a new diagram: standalone, or as a further diagram of an existing observation."""
    if observation_id is not None:
        get_or_404(db, Observation, observation_id, "Observation")
    snapshot = TacticalSnapshot(observation_id=observation_id)
    db.add(snapshot)
    with saving_files(db) as files:
        apply(db, snapshot, data, files)
    return snapshot


def update_snapshot(db: Session, snapshot_id: int, data: SnapshotIn) -> TacticalSnapshot:
    snapshot = get_or_404(db, TacticalSnapshot, snapshot_id, "Diagram")
    with saving_files(db) as files:
        apply(db, snapshot, data, files)
    return snapshot


def frame_file(snapshot: TacticalSnapshot) -> tuple[Path, str]:
    """The saved picture of a diagram and its media type. NotFound when there is none."""
    if not snapshot.frame_image_path:
        raise NotFound("This diagram has no saved frame picture.")
    path = config.FRAMES_DIR / Path(snapshot.frame_image_path).name
    if not path.is_file():
        raise NotFound("The frame picture of this diagram is missing from the data folder.")
    return path, _FRAME_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


def frame_image_url(snapshot: TacticalSnapshot) -> str | None:
    if not snapshot.frame_image_path:
        return None
    # The picture's own (random) name is part of the address, so a replaced
    # picture gets a new address and the browser never shows a stale one.
    return f"/api/snapshots/{snapshot.id}/frame?v={snapshot.frame_image_path[:12]}"


def recorded_movement(snapshot: TacticalSnapshot) -> Annotation | None:
    """The pitch arrow marked as "the run this observation is about", if there is one."""
    for annotation in snapshot.annotations:
        if (annotation.layer == "pitch" and annotation.kind == "movement"
                and annotation.properties.get("recorded_movement")):
            return annotation
    return None


def to_out(snapshot: TacticalSnapshot) -> dict:
    return {
        "id": snapshot.id, "observation_id": snapshot.observation_id, "title": snapshot.title,
        "notes": snapshot.notes, "frame_width": snapshot.frame_width, "frame_height": snapshot.frame_height,
        "frame_source": snapshot.frame_source, "frame_image_url": frame_image_url(snapshot),
        "pitch_length_m": snapshot.pitch_length_m, "pitch_width_m": snapshot.pitch_width_m,
        "annotations": [AnnotationOut.model_validate(annotation) for annotation in snapshot.annotations],
        "created_at": snapshot.created_at, "updated_at": snapshot.updated_at,
    }


def to_summary(snapshot: TacticalSnapshot) -> dict:
    layers = {annotation.layer for annotation in snapshot.annotations}
    observation = snapshot.observation
    return {
        "id": snapshot.id, "observation_id": snapshot.observation_id, "title": snapshot.title,
        "frame_image_url": frame_image_url(snapshot),
        "has_frame_layer": "frame" in layers or snapshot.frame_image_path is not None,
        "has_pitch_layer": "pitch" in layers,
        "shape_count": len(snapshot.annotations), "updated_at": snapshot.updated_at,
        "observation_category": observation.category if observation else None,
        "match": observation.match if observation else None,
        "video_time_seconds": observation.video_time_seconds if observation else None,
    }


def list_standalone(db: Session) -> list[TacticalSnapshot]:
    """Diagrams made on the Tactical Pitch page that belong to no observation."""
    return list(db.scalars(select(TacticalSnapshot).where(TacticalSnapshot.observation_id.is_(None))
                           .order_by(TacticalSnapshot.updated_at.desc())))


def list_for_player(db: Session, player_id: int) -> list[TacticalSnapshot]:
    """Every diagram drawn for an observation that involves this player, newest first."""
    get_or_404(db, Player, player_id, "Player")
    return list(db.scalars(
        select(TacticalSnapshot)
        .join(Observation, TacticalSnapshot.observation_id == Observation.id)
        .join(ObservationPlayer, ObservationPlayer.observation_id == Observation.id)
        .where(ObservationPlayer.player_id == player_id)
        .order_by(TacticalSnapshot.updated_at.desc())
    ))
