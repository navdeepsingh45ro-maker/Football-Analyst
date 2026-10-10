"""The coaching notebook: what you learn, and what you would train because of it.

    Observation >──< CoachingNote ──< TrainingIdea >──< Observation

The link tables are what keep your reasoning traceable. A note or a drill that
came from an observation stays connected to it, so months later you can still
see WHY you wrote it.

Deleting an observation removes only the link; the note or training idea stays.
"""
from sqlalchemy import JSON, CheckConstraint, Column, ForeignKey, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.common import TimestampMixin
from models.match_model import Match
from models.observation_model import Observation
from models.player_model import Player

coaching_note_observations = Table(
    "coaching_note_observations",
    Base.metadata,
    Column("coaching_note_id", ForeignKey("coaching_notes.id", ondelete="CASCADE"), primary_key=True),
    Column("observation_id", ForeignKey("observations.id", ondelete="CASCADE"), primary_key=True, index=True),
)

training_idea_observations = Table(
    "training_idea_observations",
    Base.metadata,
    Column("training_idea_id", ForeignKey("training_ideas.id", ondelete="CASCADE"), primary_key=True),
    Column("observation_id", ForeignKey("observations.id", ondelete="CASCADE"), primary_key=True, index=True),
)


class CoachingNote(Base, TimestampMixin):
    __tablename__ = "coaching_notes"
    __table_args__ = (CheckConstraint("status IS NULL OR status IN ('open', 'done')", name="status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    note_type: Mapped[str] = mapped_column(String(60), index=True)  # suggestions in vocabulary.NOTE_TYPES
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Only for things you can finish: questions to answer and goals to reach.
    # Open ones appear on the dashboard as outstanding tasks.
    status: Mapped[str | None] = mapped_column(String(10), index=True)
    # Optional context. SET NULL: the note outlives the player or match it mentions.
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id", ondelete="SET NULL"), index=True)
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id", ondelete="SET NULL"), index=True)

    player: Mapped[Player | None] = relationship()
    match: Mapped[Match | None] = relationship()
    observations: Mapped[list[Observation]] = relationship(
        secondary=coaching_note_observations, back_populates="coaching_notes"
    )
    training_ideas: Mapped[list["TrainingIdea"]] = relationship(back_populates="source_note")


class TrainingIdea(Base, TimestampMixin):
    __tablename__ = "training_ideas"
    __table_args__ = (
        CheckConstraint("duration_minutes IS NULL OR duration_minutes > 0", name="duration_minutes"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    objective: Mapped[str | None] = mapped_column(Text)  # what the players should get better at
    setup: Mapped[str | None] = mapped_column(Text)  # area, numbers, equipment
    instructions: Mapped[str | None] = mapped_column(Text)  # how it runs
    coaching_points: Mapped[str | None] = mapped_column(Text)  # what to look for and correct
    duration_minutes: Mapped[int | None]
    players_needed: Mapped[str | None] = mapped_column(String(80))  # text, e.g. "6 + GK"
    # The coaching note this drill grew out of, if any.
    source_note_id: Mapped[int | None] = mapped_column(ForeignKey("coaching_notes.id", ondelete="SET NULL"), index=True)

    source_note: Mapped[CoachingNote | None] = relationship(back_populates="training_ideas")
    observations: Mapped[list[Observation]] = relationship(
        secondary=training_idea_observations, back_populates="training_ideas"
    )
