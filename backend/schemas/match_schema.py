"""Schemas for matches, lineups and video references."""
from datetime import date
from typing import Literal

from pydantic import Field, field_validator, model_validator

from schemas.common import (
    InputSchema, NamedBrief, OptDate, OptMinute, OptScore, OptShirtNumber, OptText, OutputSchema, RequiredText,
    UtcDateTime,
)
from schemas.player_schema import PlayerBrief


class MatchIn(InputSchema):
    # Teams, competition and season are given by NAME; a new name creates the entry.
    home_team: RequiredText = Field(max_length=120)
    away_team: RequiredText = Field(max_length=120)
    competition: OptText = Field(default=None, max_length=120)
    season: OptText = Field(default=None, max_length=40)
    match_date: OptDate = None
    venue: OptText = Field(default=None, max_length=160)
    home_score: OptScore = None
    away_score: OptScore = None
    home_formation: OptText = Field(default=None, max_length=40)
    away_formation: OptText = Field(default=None, max_length=40)
    notes: OptText = None

    @field_validator("match_date")
    @classmethod
    def _date_is_plausible(cls, value: date | None):
        if value is not None and not (1863 <= value.year <= date.today().year + 2):
            raise ValueError("is not a plausible match date")
        return value

    @model_validator(mode="after")
    def _check_teams_and_score(self):
        if self.home_team.casefold() == self.away_team.casefold():
            raise ValueError("home and away team must be different")
        if (self.home_score is None) != (self.away_score is None):
            raise ValueError("enter both scores, or leave both empty if the result is unknown")
        return self


class AppearanceIn(InputSchema):
    player_id: int
    side: Literal["home", "away"]
    is_starter: bool = True
    shirt_number: OptShirtNumber = None
    position: OptText = Field(default=None, max_length=20)
    minute_on: OptMinute = None
    minute_off: OptMinute = None

    @model_validator(mode="after")
    def _minutes_make_sense(self):
        if self.is_starter and self.minute_on not in (None, 0):
            raise ValueError("a starter has no 'came on' minute; untick 'started' for a substitute")
        if self.minute_on is not None and self.minute_off is not None and self.minute_off <= self.minute_on:
            raise ValueError("'went off' must be later than 'came on'")
        return self


class AppearanceOut(OutputSchema):
    id: int
    match_id: int
    player: PlayerBrief
    team: NamedBrief
    side: str  # "home" or "away"
    is_starter: bool
    shirt_number: int | None
    position: str | None
    minute_on: int | None
    minute_off: int | None


class VideoIn(InputSchema):
    label: OptText = Field(default=None, max_length=120)
    # A file path on this computer, or a web link.
    location: RequiredText = Field(max_length=1000)
    # Normally left out: the app works it out from the location.
    kind: Literal["local_file", "direct_url", "youtube", "external_link"] | None = None
    notes: OptText = None


class Playback(OutputSchema):
    """What the app can really do with a video. Storing a link is not the same as playing it."""

    mode: Literal["html5", "embed", "none"]  # html5 = the app's own player; embed = someone else's player
    source_url: str | None  # what the player should load, when there is one
    available: bool  # False when a local file is missing right now
    can_read_time: bool  # can the app read the current position by itself
    can_capture_frames: Literal["yes", "no", "depends"]
    explanation: str  # plain-language reason, shown next to the video


class VideoOut(OutputSchema):
    id: int
    match_id: int
    label: str
    kind: str
    location: str
    notes: str | None
    playback: Playback


class MatchBrief(OutputSchema):
    id: int
    title: str  # "Home v Away"
    match_date: date | None


class MatchOut(OutputSchema):
    id: int
    title: str
    home_team: NamedBrief
    away_team: NamedBrief
    competition: NamedBrief | None
    season: NamedBrief | None
    match_date: date | None
    venue: str | None
    home_score: int | None
    away_score: int | None
    home_formation: str | None
    away_formation: str | None
    notes: str | None
    created_at: UtcDateTime
    updated_at: UtcDateTime


class MatchListItem(MatchOut):
    observation_count: int
    video_count: int


class MatchDetail(MatchOut):
    appearances: list[AppearanceOut]
    videos: list[VideoOut]
    observation_count: int
