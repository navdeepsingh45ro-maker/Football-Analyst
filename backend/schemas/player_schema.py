"""Schemas for players."""
from datetime import date
from typing import Literal

from pydantic import Field, field_validator, model_validator

import vocabulary
from schemas.common import (
    InputSchema, NamedBrief, OptDate, OptHeightCm, OptShirtNumber, OptText, OutputSchema, RequiredText,
    UtcDateTime, http_url,
)


class PlayerIn(InputSchema):
    """Everything about a player that can be typed in. Only the name is required."""

    full_name: RequiredText = Field(max_length=160)
    photo_url: OptText = Field(default=None, max_length=500)
    date_of_birth: OptDate = None
    nationality: OptText = Field(default=None, max_length=80)
    height_cm: OptHeightCm = None
    preferred_foot: Literal["left", "right", "both"] | None = None
    primary_position: OptText = Field(default=None, max_length=20)
    secondary_positions: list[str] = []
    # Teams are given by NAME. A name not seen before creates the team.
    current_team: OptText = Field(default=None, max_length=120)
    national_team: OptText = Field(default=None, max_length=120)
    shirt_number: OptShirtNumber = None
    notes: OptText = None

    @field_validator("preferred_foot", mode="before")
    @classmethod
    def _blank_foot_is_unknown(cls, value):
        return value or None

    @field_validator("photo_url")
    @classmethod
    def _photo_must_be_a_web_link(cls, value):
        return http_url(value)

    @field_validator("date_of_birth")
    @classmethod
    def _birth_date_is_plausible(cls, value: date | None):
        if value is not None and not (date(1900, 1, 1) <= value <= date.today()):
            raise ValueError("must be between 1900 and today")
        return value

    @field_validator("primary_position")
    @classmethod
    def _tidy_position(cls, value):
        return vocabulary.canonical(value, vocabulary.POSITIONS)

    @model_validator(mode="after")
    def _tidy_secondary_positions(self):
        # Same spelling as the suggestions, no blanks, no repeats, and not the primary again.
        tidy: list[str] = []
        for raw in self.secondary_positions:
            position = vocabulary.canonical(raw, vocabulary.POSITIONS)
            if position and position != self.primary_position and position not in tidy:
                tidy.append(position)
        self.secondary_positions = tidy
        return self


class PlayerBrief(OutputSchema):
    """A player as shown inside another record (a lineup, an observation)."""

    id: int
    full_name: str
    primary_position: str | None


class PlayerOut(OutputSchema):
    id: int
    full_name: str
    photo_url: str | None
    date_of_birth: date | None
    age: int | None  # worked out from date_of_birth; None when the birth date is unknown
    nationality: str | None
    height_cm: int | None
    preferred_foot: str | None
    primary_position: str | None
    secondary_positions: list[str]
    current_team: NamedBrief | None
    national_team: NamedBrief | None
    shirt_number: int | None
    notes: str | None
    created_at: UtcDateTime
    updated_at: UtcDateTime


class PlayerListItem(PlayerOut):
    observation_count: int
    latest_assessment_on: date | None


class PlayerCounts(OutputSchema):
    """How much is recorded about a player; drives the numbers on the profile tabs."""

    observations: int
    assessments: int
    appearances: int
    statistics: int
    diagrams: int
    notes: int


class PlayerDetail(PlayerOut):
    counts: PlayerCounts


class TimelineEvent(OutputSchema):
    """One entry in a player's history. `date` is None when the match date is unknown."""

    kind: Literal["assessment", "observation", "appearance", "note"]
    date: date | None
    title: str
    detail: str | None
    record_id: int
    match_id: int | None = None
