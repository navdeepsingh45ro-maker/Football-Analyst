"""Schemas for scouting assessments (dated, subjective opinions about a player)."""
from datetime import date

from pydantic import Field, field_validator, model_validator

import vocabulary
from models import ASSESSMENT_SECTIONS
from schemas.common import InputSchema, OptText, OutputSchema, UtcDateTime


class RatingIn(InputSchema):
    attribute: str
    rating: int = Field(ge=vocabulary.RATING_MIN, le=vocabulary.RATING_MAX)
    note: OptText = None

    @field_validator("attribute")
    @classmethod
    def _attribute_is_known(cls, value: str):
        if value not in vocabulary.RATING_ATTRIBUTES:
            raise ValueError(f"unknown attribute; use one of: {', '.join(vocabulary.RATING_ATTRIBUTES)}")
        return value


class AssessmentIn(InputSchema):
    assessed_on: date = Field(default_factory=date.today)
    basis: OptText = Field(default=None, max_length=300)  # what the opinion rests on
    summary: OptText = None
    playing_style: OptText = None
    tactical_role: OptText = None
    technical_strengths: OptText = None
    tactical_strengths: OptText = None
    physical_characteristics: OptText = None
    weaknesses: OptText = None
    development_opportunities: OptText = None
    ratings: list[RatingIn] = []

    @field_validator("assessed_on")
    @classmethod
    def _not_in_the_future(cls, value: date):
        if value > date.today():
            raise ValueError("an assessment cannot be dated in the future")
        return value

    @model_validator(mode="after")
    def _check_content(self):
        attributes = [rating.attribute for rating in self.ratings]
        if len(attributes) != len(set(attributes)):
            raise ValueError("each attribute can be rated only once per assessment")
        has_text = self.summary or any(getattr(self, section) for section in ASSESSMENT_SECTIONS)
        if not has_text and not self.ratings:
            raise ValueError("an assessment needs at least a summary, one section or one rating")
        return self


class RatingOut(OutputSchema):
    attribute: str
    rating: int
    note: str | None


class AssessmentOut(OutputSchema):
    id: int
    player_id: int
    assessed_on: date
    basis: str | None
    summary: str | None
    playing_style: str | None
    tactical_role: str | None
    technical_strengths: str | None
    tactical_strengths: str | None
    physical_characteristics: str | None
    weaknesses: str | None
    development_opportunities: str | None
    ratings: list[RatingOut]
    created_at: UtcDateTime
    updated_at: UtcDateTime


class RatingPoint(OutputSchema):
    assessment_id: int
    assessed_on: date
    rating: int | None  # None = this attribute was not rated in that assessment


class RatingTrend(OutputSchema):
    attribute: str
    label: str
    points: list[RatingPoint]  # oldest first, one per assessment
    first_rating: int | None  # earliest rating that exists
    latest_rating: int | None
    change: int | None  # latest minus first; None when rated fewer than twice


class RatingHistory(OutputSchema):
    """How your ratings of a player changed across assessments."""

    assessment_count: int
    scale_note: str
    trends: list[RatingTrend]
