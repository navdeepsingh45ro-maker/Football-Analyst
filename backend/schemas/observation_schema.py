"""Schemas for observations, tactical snapshots (diagrams) and the shapes drawn on them."""
import re
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

import vocabulary
from schemas.common import (
    InputSchema, OptMatchClock, OptText, OptVideoTime, OutputSchema, RequiredText, UtcDateTime, finite,
)
from schemas.match_schema import MatchBrief

_UID = re.compile(r"[A-Za-z0-9_-]{1,40}")
_SIMPLE = (str, int, float, bool, type(None))


# ── Shapes on a diagram ──────────────────────────────────────────────────────
class AnnotationIn(InputSchema):
    uid: str  # made up by the editor; identifies the shape for as long as it exists
    layer: Literal["frame", "pitch"]
    kind: str
    points: list[tuple[float, float]]  # in the LAYER'S coordinate system (see models/snapshot_model.py)
    label: OptText = Field(default=None, max_length=120)
    player_id: int | None = None  # the real player this marker stands for, if any
    properties: dict[str, Any] = {}

    @field_validator("uid")
    @classmethod
    def _uid_is_simple(cls, value: str):
        if not _UID.fullmatch(value):
            raise ValueError("must be 1-40 letters, digits, - or _")
        return value

    @field_validator("properties")
    @classmethod
    def _properties_are_small_and_simple(cls, value: dict[str, Any]):
        if len(value) > 20:
            raise ValueError("too many properties")
        for name, item in value.items():
            if not name or len(name) > 40 or not isinstance(item, _SIMPLE):
                raise ValueError("properties must be simple values with short names")
            if isinstance(item, str) and len(item) > 200:
                raise ValueError("a property text is too long")
            if isinstance(item, float):
                finite(item)
        return value

    @model_validator(mode="after")
    def _shape_is_complete(self):
        if self.kind not in vocabulary.ANNOTATION_KINDS:
            raise ValueError(f"unknown kind of shape: {self.kind}")
        fewest, most = vocabulary.ANNOTATION_KINDS[self.kind]
        if not (fewest <= len(self.points) <= most):
            needed = str(fewest) if fewest == most else f"{fewest} to {most}"
            raise ValueError(f"a {self.kind} needs {needed} point(s), got {len(self.points)}")
        for x, y in self.points:
            finite(x)
            finite(y)
        return self


class AnnotationOut(OutputSchema):
    uid: str
    layer: str
    kind: str
    points: list[tuple[float, float]]
    label: str | None
    player_id: int | None
    properties: dict[str, Any]
    z_index: int


# ── Diagrams ─────────────────────────────────────────────────────────────────
class SnapshotIn(InputSchema):
    """A diagram as the editor sends it. Saving REPLACES the diagram's shapes with this list."""

    title: OptText = Field(default=None, max_length=200)
    notes: OptText = None

    # The frame layer: the real size of the frame in pixels, and optionally its picture.
    frame_width: int | None = Field(default=None, gt=0, le=20_000)
    frame_height: int | None = Field(default=None, gt=0, le=20_000)
    # A picture as a "data:image/...;base64,..." text. Send it only when there is a new one.
    frame_image: str | None = None
    frame_source: Literal["video_capture", "upload"] | None = None
    # When editing: True keeps the picture already stored, False removes it.
    keep_frame_image: bool = True

    # The pitch layer: its size in metres (the laws of the game allow 90-120 x 45-90).
    pitch_length_m: float = Field(default=vocabulary.PITCH_LENGTH_M, ge=90, le=120)
    pitch_width_m: float = Field(default=vocabulary.PITCH_WIDTH_M, ge=45, le=90)

    annotations: list[AnnotationIn] = Field(default=[], max_length=500)

    @model_validator(mode="after")
    def _check_coordinates(self):
        if (self.frame_width is None) != (self.frame_height is None):
            raise ValueError("give both frame_width and frame_height, or neither")
        if self.frame_image and self.frame_width is None:
            raise ValueError("a frame picture needs its width and height")

        uids = [annotation.uid for annotation in self.annotations]
        if len(uids) != len(set(uids)):
            raise ValueError("two shapes have the same uid")

        margin = vocabulary.PITCH_MARGIN_M
        for annotation in self.annotations:
            for x, y in annotation.points:
                if annotation.layer == "frame":
                    if self.frame_width is None:
                        raise ValueError("shapes on the frame layer need the frame's width and height")
                    # Frame points are fractions of the frame, so they must lie inside it.
                    if not (0 <= x <= 1 and 0 <= y <= 1):
                        raise ValueError(
                            f"frame point ({x}, {y}) is outside the frame; frame coordinates run from 0 to 1")
                else:
                    # Pitch points are metres; a small margin allows a player just off the pitch.
                    if not (-margin <= x <= self.pitch_length_m + margin
                            and -margin <= y <= self.pitch_width_m + margin):
                        raise ValueError(f"pitch point ({x}, {y}) is outside the pitch area (metres)")

        recorded = [a for a in self.annotations
                    if a.layer == "pitch" and a.kind == "movement" and a.properties.get("recorded_movement")]
        if len(recorded) > 1:
            raise ValueError("only one arrow can be marked as the recorded movement")
        return self


class SnapshotOut(OutputSchema):
    id: int
    observation_id: int | None
    title: str | None
    notes: str | None
    frame_width: int | None
    frame_height: int | None
    frame_source: str | None
    frame_image_url: str | None  # where to load the saved picture from; None when there is none
    pitch_length_m: float
    pitch_width_m: float
    annotations: list[AnnotationOut]
    created_at: UtcDateTime
    updated_at: UtcDateTime


class SnapshotSummary(OutputSchema):
    """A diagram in a list: enough to show a card without loading every shape."""

    id: int
    observation_id: int | None
    title: str | None
    frame_image_url: str | None
    has_frame_layer: bool
    has_pitch_layer: bool
    shape_count: int
    updated_at: UtcDateTime
    # Filled in when the diagram belongs to an observation.
    observation_category: str | None = None
    match: MatchBrief | None = None
    video_time_seconds: float | None = None


# ── Observations ─────────────────────────────────────────────────────────────
class ObservationIn(InputSchema):
    # Who. The first id is the player being studied unless primary_player_id says otherwise.
    player_ids: list[int] = Field(default=[], max_length=30)
    primary_player_id: int | None = None
    # Where and when.
    match_id: int | None = None
    video_reference_id: int | None = None
    video_time_seconds: OptVideoTime = None  # position in the video; seconds or "35:10"
    match_clock_seconds: OptMatchClock = None  # scoreboard clock; seconds or "32:14"
    # What. Suggestions come from vocabulary.py; your own wording is kept as typed.
    category: RequiredText = Field(max_length=80)
    movement_category: OptText = Field(default=None, max_length=80)
    outcome: OptText = Field(default=None, max_length=80)
    tactical_situation: OptText = None
    defensive_shape: OptText = Field(default=None, max_length=80)
    movement_trigger: OptText = None
    intended_space: OptText = None
    # Your reading of it.
    notes: OptText = None
    evidence: OptText = None
    confidence: Literal["low", "medium", "high"] | None = None

    @field_validator("confidence", mode="before")
    @classmethod
    def _blank_confidence_is_unknown(cls, value):
        return value or None

    @model_validator(mode="after")
    def _tidy(self):
        self.category = vocabulary.canonical(self.category, vocabulary.OBSERVATION_CATEGORIES)
        self.movement_category = vocabulary.canonical(self.movement_category, vocabulary.MOVEMENT_CATEGORIES)
        self.outcome = vocabulary.canonical(self.outcome, vocabulary.OUTCOMES)

        if len(self.player_ids) != len(set(self.player_ids)):
            raise ValueError("a player is listed twice")
        if not self.player_ids and self.match_id is None:
            raise ValueError("an observation must be attached to at least one player or a match")
        if self.primary_player_id is not None and self.primary_player_id not in self.player_ids:
            raise ValueError("the primary player must be one of the listed players")
        if self.video_reference_id is not None and self.match_id is None:
            raise ValueError("a video belongs to a match; choose the match as well")
        return self


class ObservationCreate(ObservationIn):
    """Creating can include the diagram drawn for the observation, saved in the same step."""

    snapshot: SnapshotIn | None = None


class ObservationPlayerOut(OutputSchema):
    id: int
    full_name: str
    primary_position: str | None
    role: str  # "primary" or "involved"


class LinkedNote(OutputSchema):
    id: int
    title: str
    kind: str  # "coaching_note" or "training_idea"


class ObservationOut(OutputSchema):
    id: int  # the stable identifier
    match: MatchBrief | None
    video_reference_id: int | None
    video_time_seconds: float | None
    match_clock_seconds: int | None
    category: str
    movement_category: str | None
    outcome: str | None
    tactical_situation: str | None
    defensive_shape: str | None
    movement_trigger: str | None
    intended_space: str | None
    notes: str | None
    evidence: str | None
    confidence: str | None
    players: list[ObservationPlayerOut]
    snapshot_ids: list[int]
    created_at: UtcDateTime
    updated_at: UtcDateTime


class ObservationDetail(ObservationOut):
    snapshots: list[SnapshotOut]
    derived: list[LinkedNote]  # coaching notes and training ideas written because of this observation


class ObservationPage(OutputSchema):
    total: int  # how many observations match the filters in all
    items: list[ObservationOut]
