"""Schemas for teams, competitions and seasons."""
from typing import Literal

from pydantic import Field

from schemas.common import InputSchema, OptText, OutputSchema, RequiredText


class TeamIn(InputSchema):
    name: RequiredText = Field(max_length=120)
    team_type: Literal["club", "national"] = "club"
    country: OptText = Field(default=None, max_length=80)


class TeamOut(OutputSchema):
    id: int
    name: str
    team_type: str
    country: str | None


class CompetitionIn(InputSchema):
    name: RequiredText = Field(max_length=120)
    country: OptText = Field(default=None, max_length=80)


class CompetitionOut(OutputSchema):
    id: int
    name: str
    country: str | None


class SeasonIn(InputSchema):
    name: RequiredText = Field(max_length=40)


class SeasonOut(OutputSchema):
    id: int
    name: str
