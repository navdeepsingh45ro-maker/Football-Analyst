"""Scouting assessments: what you thought of a player on a given date.

This is how the app keeps history. Each assessment is its own dated row:

    Player ──< ScoutingAssessment ──< AssessmentRating

When your opinion changes you add a NEW assessment; the old ones stay, so you
can compare what you believed in March with what you believe in October.
Editing an assessment is possible (to fix a typo) but is not how opinions evolve.

Everything here is subjective. Ratings use the explicit 1-5 scale defined in
vocabulary.py and are never mixed into the measured statistics.
"""
from datetime import date

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.common import TimestampMixin

# The free-text sections of an assessment, in display order (key -> heading).
ASSESSMENT_SECTIONS = {
    "playing_style": "Playing style",
    "tactical_role": "Tactical role",
    "technical_strengths": "Technical strengths",
    "tactical_strengths": "Tactical strengths",
    "physical_characteristics": "Physical characteristics",
    "weaknesses": "Weaknesses",
    "development_opportunities": "Development opportunities",
}


class ScoutingAssessment(Base, TimestampMixin):
    __tablename__ = "scouting_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="RESTRICT"), index=True)
    assessed_on: Mapped[date] = mapped_column(index=True)  # the date the opinion was formed
    basis: Mapped[str | None] = mapped_column(String(300))  # e.g. "Three league matches in October"
    summary: Mapped[str | None] = mapped_column(Text)

    playing_style: Mapped[str | None] = mapped_column(Text)
    tactical_role: Mapped[str | None] = mapped_column(Text)
    technical_strengths: Mapped[str | None] = mapped_column(Text)
    tactical_strengths: Mapped[str | None] = mapped_column(Text)
    physical_characteristics: Mapped[str | None] = mapped_column(Text)
    weaknesses: Mapped[str | None] = mapped_column(Text)
    development_opportunities: Mapped[str | None] = mapped_column(Text)

    ratings: Mapped[list["AssessmentRating"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan", passive_deletes=True,
        order_by="AssessmentRating.id",
    )


class AssessmentRating(Base):
    """One subjective 1-5 rating inside an assessment, e.g. first_touch = 4."""

    __tablename__ = "assessment_ratings"
    __table_args__ = (
        UniqueConstraint("assessment_id", "attribute", name="uq_assessment_ratings_assessment_attribute"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("scouting_assessments.id", ondelete="CASCADE"), index=True)
    attribute: Mapped[str] = mapped_column(String(40))  # a key from vocabulary.RATING_ATTRIBUTES
    rating: Mapped[int]
    note: Mapped[str | None] = mapped_column(Text)

    assessment: Mapped[ScoutingAssessment] = relationship(back_populates="ratings")
