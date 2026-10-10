"""Schemas for the coaching notebook: coaching notes and training ideas."""
from typing import Literal

from pydantic import Field, field_validator, model_validator

import vocabulary
from schemas.common import InputSchema, OptText, OutputSchema, RequiredText, UtcDateTime
from schemas.match_schema import MatchBrief
from schemas.player_schema import PlayerBrief

OptDuration = int | None


def _unique_ids(values: list[int]) -> list[int]:
    if len(values) != len(set(values)):
        raise ValueError("an observation is listed twice")
    return values


class CoachingNoteIn(InputSchema):
    note_type: RequiredText = Field(max_length=60)  # suggestions in vocabulary.NOTE_TYPES; your own wording is kept
    title: RequiredText = Field(max_length=200)
    body: OptText = None
    tags: list[str] = []
    status: Literal["open", "done"] | None = None  # for questions and goals: still open, or dealt with
    player_id: int | None = None
    match_id: int | None = None
    # The observations this note was written because of. This is the "why" trail.
    observation_ids: list[int] = Field(default=[], max_length=200)

    @field_validator("status", mode="before")
    @classmethod
    def _blank_status_is_none(cls, value):
        return value or None

    @field_validator("observation_ids")
    @classmethod
    def _no_repeats(cls, value):
        return _unique_ids(value)

    @model_validator(mode="after")
    def _tidy(self):
        self.note_type = vocabulary.canonical(self.note_type, vocabulary.NOTE_TYPES)
        tidy: list[str] = []
        for raw in self.tags:
            tag = " ".join(str(raw).split())
            if tag and len(tag) <= 40 and tag.casefold() not in [t.casefold() for t in tidy]:
                tidy.append(tag)
        if len(tidy) > 20:
            raise ValueError("at most 20 tags")
        self.tags = tidy
        return self


class TrainingIdeaIn(InputSchema):
    title: RequiredText = Field(max_length=200)
    objective: OptText = None  # what the players should get better at
    setup: OptText = None  # area, numbers, equipment
    instructions: OptText = None  # how it runs
    coaching_points: OptText = None  # what to look for and correct
    duration_minutes: OptDuration = Field(default=None, ge=1, le=600)
    players_needed: OptText = Field(default=None, max_length=80)
    source_note_id: int | None = None  # the coaching note this grew out of
    observation_ids: list[int] = Field(default=[], max_length=200)

    @field_validator("duration_minutes", mode="before")
    @classmethod
    def _blank_duration_is_unknown(cls, value):
        return None if value == "" else value

    @field_validator("observation_ids")
    @classmethod
    def _no_repeats(cls, value):
        return _unique_ids(value)


class ObservationRef(OutputSchema):
    """An observation as shown in a note's "written because of" list."""

    id: int
    category: str
    movement_category: str | None
    video_time_seconds: float | None
    match: MatchBrief | None


class NoteRef(OutputSchema):
    id: int
    title: str


class CoachingNoteOut(OutputSchema):
    id: int
    note_type: str
    title: str
    body: str | None
    tags: list[str]
    status: str | None
    player: PlayerBrief | None
    match: MatchBrief | None
    observations: list[ObservationRef]
    training_ideas: list[NoteRef]  # drills that grew out of this note
    created_at: UtcDateTime
    updated_at: UtcDateTime


class TrainingIdeaOut(OutputSchema):
    id: int
    title: str
    objective: str | None
    setup: str | None
    instructions: str | None
    coaching_points: str | None
    duration_minutes: int | None
    players_needed: str | None
    source_note: NoteRef | None
    observations: list[ObservationRef]
    created_at: UtcDateTime
    updated_at: UtcDateTime
