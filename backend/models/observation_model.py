"""Observations: the central record of the whole app.

An observation is ONE thing you noticed: who, in which match, at what point in
the video, what kind of thing it was, and what you make of it.

    Match ──< Observation >──< Player          (through ObservationPlayer)
                  │
                  ├──< TacticalSnapshot        (the diagram(s) drawn for it)
                  ├──< CoachingNote            (notes written because of it)
                  └──< TrainingIdea

Its `id` is the stable identifier: editing an observation changes the row in
place and never creates a second copy.

THREE DIFFERENT KINDS OF TIME, never mixed up:
    created_at / updated_at   calendar moments (UTC) when YOU wrote the record
    video_time_seconds        position inside the video file, e.g. 2110.4 = 35:10
    match_clock_seconds       the clock on the scoreboard, e.g. 1934 = 32:14
A video usually starts before kick-off, so the last two differ. Both are optional.
"""
from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.common import TimestampMixin
from models.match_model import Match, VideoReference
from models.player_model import Player


class Observation(Base, TimestampMixin):
    __tablename__ = "observations"
    __table_args__ = (
        CheckConstraint("confidence IS NULL OR confidence IN ('low', 'medium', 'high')", name="confidence"),
        CheckConstraint("video_time_seconds IS NULL OR video_time_seconds >= 0", name="video_time_seconds"),
        CheckConstraint("match_clock_seconds IS NULL OR match_clock_seconds >= 0", name="match_clock_seconds"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # RESTRICT: a match that has observations cannot be deleted by accident.
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id", ondelete="RESTRICT"), index=True)
    # SET NULL: removing a video link keeps the observation and its timestamp.
    video_reference_id: Mapped[int | None] = mapped_column(ForeignKey("video_references.id", ondelete="SET NULL"))
    video_time_seconds: Mapped[float | None]
    match_clock_seconds: Mapped[int | None]

    # What was observed. Free text with suggestions (see vocabulary.py).
    category: Mapped[str] = mapped_column(String(80), index=True)
    movement_category: Mapped[str | None] = mapped_column(String(80), index=True)
    outcome: Mapped[str | None] = mapped_column(String(80), index=True)

    # The situation, as you describe it.
    tactical_situation: Mapped[str | None] = mapped_column(Text)
    defensive_shape: Mapped[str | None] = mapped_column(String(80))  # e.g. "4-4-2 mid block"
    movement_trigger: Mapped[str | None] = mapped_column(Text)  # what set the movement off
    intended_space: Mapped[str | None] = mapped_column(Text)  # the space being attacked

    # Your interpretation and how sure you are of it.
    notes: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[str | None] = mapped_column(Text)  # other references: links, clip names, page numbers
    confidence: Mapped[str | None] = mapped_column(String(10))

    match: Mapped[Match | None] = relationship()
    video_reference: Mapped[VideoReference | None] = relationship()
    player_links: Mapped[list["ObservationPlayer"]] = relationship(
        back_populates="observation", cascade="all, delete-orphan", passive_deletes=True
    )
    snapshots: Mapped[list["TacticalSnapshot"]] = relationship(  # noqa: F821
        back_populates="observation", cascade="all, delete-orphan", passive_deletes=True,
        order_by="TacticalSnapshot.id",
    )
    coaching_notes: Mapped[list["CoachingNote"]] = relationship(  # noqa: F821
        secondary="coaching_note_observations", back_populates="observations"
    )
    training_ideas: Mapped[list["TrainingIdea"]] = relationship(  # noqa: F821
        secondary="training_idea_observations", back_populates="observations"
    )

    @property
    def players(self) -> list[Player]:
        """The players in this observation, the primary subject first."""
        ordered = sorted(self.player_links, key=lambda link: (link.role != "primary", link.player.full_name))
        return [link.player for link in ordered]


class ObservationPlayer(Base):
    """Links a player to an observation. Several players can share one situation."""

    __tablename__ = "observation_players"
    __table_args__ = (CheckConstraint("role IN ('primary', 'involved')", name="role"),)

    observation_id: Mapped[int] = mapped_column(ForeignKey("observations.id", ondelete="CASCADE"), primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="RESTRICT"), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(10), default="primary")  # "primary" = the player being studied

    observation: Mapped[Observation] = relationship(back_populates="player_links")
    player: Mapped[Player] = relationship()
