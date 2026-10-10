"""Tactical snapshots: a saved diagram, and the shapes drawn on it.

    Observation ──< TacticalSnapshot ──< Annotation

A snapshot has up to two LAYERS, and each layer has its own coordinate system.
They are deliberately NOT interchangeable:

    layer "frame"   drawn over a video frame.
                    Points are fractions of the frame: x and y between 0 and 1,
                    (0, 0) = top-left corner, (1, 1) = bottom-right corner.
                    frame_width / frame_height record the frame's real size in
                    pixels, so the picture can be rebuilt at any screen size.
                    A camera image is distorted by perspective, so NO real-world
                    distance can be read from this layer.

    layer "pitch"   placed on the top-down pitch diagram.
                    Points are METRES on a pitch_length_m x pitch_width_m pitch:
                    x = 0 is the goal line of the team you are studying,
                    x = pitch_length_m is the goal line they attack,
                    y = 0 is the touchline on their left as they attack.
                    Distances and angles here are estimates, because you placed
                    the markers by eye.

Nothing is ever stored in screen pixels, which is why a diagram still lines up
after the window is resized or opened on another screen.

A snapshot with no observation is a standalone diagram made on the Tactical Pitch page.
"""
from sqlalchemy import JSON, CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

import vocabulary
from database import Base
from models.common import TimestampMixin
from models.observation_model import Observation
from models.player_model import Player


class TacticalSnapshot(Base, TimestampMixin):
    __tablename__ = "tactical_snapshots"
    __table_args__ = (
        CheckConstraint(
            "(frame_width IS NULL AND frame_height IS NULL) OR (frame_width > 0 AND frame_height > 0)",
            name="frame_size",
        ),
        CheckConstraint("frame_source IS NULL OR frame_source IN ('video_capture', 'upload')", name="frame_source"),
        CheckConstraint("pitch_length_m > 0 AND pitch_width_m > 0", name="pitch_size"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # CASCADE: a diagram drawn for an observation is deleted with that observation.
    observation_id: Mapped[int | None] = mapped_column(ForeignKey("observations.id", ondelete="CASCADE"), index=True)
    title: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)

    # The frame layer's picture: a file name inside data/media/frames, if one was saved.
    frame_image_path: Mapped[str | None] = mapped_column(String(300))
    frame_width: Mapped[int | None]  # pixels of the original frame
    frame_height: Mapped[int | None]
    frame_source: Mapped[str | None] = mapped_column(String(20))

    # The pitch layer's size in metres.
    pitch_length_m: Mapped[float] = mapped_column(default=vocabulary.PITCH_LENGTH_M)
    pitch_width_m: Mapped[float] = mapped_column(default=vocabulary.PITCH_WIDTH_M)

    observation: Mapped[Observation | None] = relationship(back_populates="snapshots")
    annotations: Mapped[list["Annotation"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan", passive_deletes=True,
        order_by="Annotation.z_index",
    )


class Annotation(Base):
    """One shape on a diagram: a player marker, the ball, an arrow, a zone, an angle, a label."""

    __tablename__ = "annotations"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "uid", name="uq_annotations_snapshot_uid"),
        CheckConstraint("layer IN ('frame', 'pitch')", name="layer"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("tactical_snapshots.id", ondelete="CASCADE"), index=True)
    # Made up by the editor when the shape is drawn and kept for its whole life,
    # so a shape keeps its identity even though saving rewrites the rows.
    uid: Mapped[str] = mapped_column(String(40))
    layer: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(20))  # a key from vocabulary.ANNOTATION_KINDS
    points: Mapped[list] = mapped_column(JSON)  # [[x, y], ...] in the layer's coordinate system
    label: Mapped[str | None] = mapped_column(String(120))
    # A marker can stand for a real player. SET NULL: the marker stays if the player is deleted.
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id", ondelete="SET NULL"), index=True)
    # Extras that depend on the kind, e.g. {"number": 9}, {"zone_type": "Half-space"},
    # {"recorded_movement": true} for the run this observation is about.
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    z_index: Mapped[int] = mapped_column(default=0)  # drawing order, lowest first

    snapshot: Mapped[TacticalSnapshot] = relationship(back_populates="annotations")
    player: Mapped[Player | None] = relationship()
