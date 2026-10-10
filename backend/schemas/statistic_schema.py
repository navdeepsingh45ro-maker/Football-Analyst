"""Schemas for measured statistics (one "stat line" = one player in one match or one season)."""
from typing import Literal

from pydantic import Field, field_validator, model_validator

from models import STAT_FIELDS
from schemas.common import (
    InputSchema, NamedBrief, OptCount, OptText, OutputSchema, RequiredText, UtcDateTime, finite, http_url,
)
from schemas.match_schema import MatchBrief


class StatisticIn(InputSchema):
    scope: Literal["match", "season"]
    # For scope "match": which match. Season, competition and team then come from the match.
    match_id: int | None = None
    # For scope "season": given by NAME (a new name creates the entry).
    season: OptText = Field(default=None, max_length=40)
    competition: OptText = Field(default=None, max_length=120)
    team: OptText = Field(default=None, max_length=120)

    # Every number is optional. Leave a field empty when you do not know it:
    # empty is stored as "not recorded" and is never counted as 0.
    appearances: OptCount = None
    minutes_played: OptCount = None
    goals: OptCount = None
    assists: OptCount = None
    shots: OptCount = None
    shots_on_target: OptCount = None
    chances_created: OptCount = None
    passes_completed: OptCount = None
    passes_attempted: OptCount = None
    dribbles_completed: OptCount = None
    duels_won: OptCount = None
    duels_contested: OptCount = None
    extra_metrics: dict[str, float] = {}  # position-specific numbers, e.g. {"saves": 4}

    source: RequiredText = Field(max_length=200)  # where the numbers came from
    source_url: OptText = Field(default=None, max_length=500)
    notes: OptText = None

    @field_validator("source_url")
    @classmethod
    def _source_url_is_a_web_link(cls, value):
        return http_url(value)

    @field_validator("extra_metrics")
    @classmethod
    def _tidy_extra_metrics(cls, value: dict[str, float]):
        tidy: dict[str, float] = {}
        for name, number in value.items():
            name = " ".join(name.split())
            if not name or len(name) > 40:
                raise ValueError("each extra metric needs a name of 1 to 40 characters")
            tidy[name] = finite(number)
        return tidy

    @model_validator(mode="after")
    def _check_the_line_makes_sense(self):
        if self.scope == "match":
            if self.match_id is None:
                raise ValueError("a match stat line needs a match")
            if self.season or self.competition or self.team:
                raise ValueError("for a match stat line, season, competition and team come from the match itself")
            if self.appearances is not None:
                raise ValueError("'appearances' only applies to a season stat line")
            if self.minutes_played is not None and self.minutes_played > 130:
                raise ValueError("minutes played in one match cannot be more than 130")
        else:
            if self.match_id is not None:
                raise ValueError("a season stat line cannot point at a single match")
            if not self.season:
                raise ValueError("a season stat line needs a season")

        # A part cannot be bigger than its whole (only checked when both are known).
        for part, whole in (("shots_on_target", "shots"), ("passes_completed", "passes_attempted"),
                            ("duels_won", "duels_contested")):
            part_value, whole_value = getattr(self, part), getattr(self, whole)
            if part_value is not None and whole_value is not None and part_value > whole_value:
                raise ValueError(f"{part.replace('_', ' ')} cannot be more than {whole.replace('_', ' ')}")

        if all(getattr(self, name) is None for name in STAT_FIELDS) and not self.extra_metrics:
            raise ValueError("enter at least one number; an empty stat line records nothing")
        return self


class StatisticOut(OutputSchema):
    id: int
    player_id: int
    scope: str
    context: str  # readable description of what the numbers cover
    match: MatchBrief | None
    season: NamedBrief | None
    competition: NamedBrief | None
    team: NamedBrief | None
    appearances: int | None
    minutes_played: int | None
    goals: int | None
    assists: int | None
    shots: int | None
    shots_on_target: int | None
    chances_created: int | None
    passes_completed: int | None
    passes_attempted: int | None
    dribbles_completed: int | None
    duels_won: int | None
    duels_contested: int | None
    extra_metrics: dict[str, float]
    source: str
    source_url: str | None
    notes: str | None
    created_at: UtcDateTime
    updated_at: UtcDateTime
