"""Building blocks shared by every schema.

A schema describes the JSON the API accepts or returns. Pydantic checks incoming
data against it BEFORE any of our code runs, so a route can trust what it gets.

THE "UNKNOWN STAYS UNKNOWN" RULE
--------------------------------
An empty form field arrives as "" or as nothing at all. The Opt... types below
turn every such value into None, which the database stores as NULL. So an
unknown height is NULL, not 0 and not "" - and nothing later can mistake it
for a real value.

EDITING = SENDING THE WHOLE RECORD AGAIN
----------------------------------------
Each thing you can edit has ONE input schema, used both to create it (POST) and
to replace it (PUT). The edit forms always send every field, so there is one set
of validation rules per record and no special "partial update" logic to get wrong.
"""
import math
from datetime import date, datetime, timezone
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _strip(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


# Optional values: blank means unknown (None).
OptText = Annotated[str | None, BeforeValidator(_blank_to_none)]
OptInt = Annotated[int | None, BeforeValidator(_blank_to_none)]
OptFloat = Annotated[float | None, BeforeValidator(_blank_to_none)]
OptDate = Annotated[date | None, BeforeValidator(_blank_to_none)]

# Optional whole numbers with a sensible range. Note where the range sits: on the
# `int` INSIDE the "or None", so the rule is only ever applied to a real number.
# (Written the other way round, a blank field would be checked as "None >= 0" and crash.)
OptCount = Annotated[Annotated[int, Field(ge=0)] | None, BeforeValidator(_blank_to_none)]  # how many
OptScore = Annotated[Annotated[int, Field(ge=0, le=99)] | None, BeforeValidator(_blank_to_none)]
OptMinute = Annotated[Annotated[int, Field(ge=0, le=130)] | None, BeforeValidator(_blank_to_none)]
OptShirtNumber = Annotated[Annotated[int, Field(ge=1, le=99)] | None, BeforeValidator(_blank_to_none)]
OptHeightCm = Annotated[Annotated[int, Field(ge=120, le=230)] | None, BeforeValidator(_blank_to_none)]

def clock_to_seconds(value: Any) -> Any:
    """Accept a position in a video either as seconds (2110.4) or as a clock ("35:10", "1:02:03").

    This is a VIDEO or MATCH clock, not a time of day: "35:10" means 35 minutes
    and 10 seconds from the start, which is 2110 seconds.
    """
    value = _blank_to_none(value)
    if value is None or not isinstance(value, str):
        return value
    parts = value.split(":")
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        raise ValueError('must be seconds or a clock like "32:14" or "1:02:03"') from None
    if len(numbers) > 3 or any(n < 0 for n in numbers) or any(n >= 60 for n in numbers[1:]):
        raise ValueError('must be seconds or a clock like "32:14" or "1:02:03"')
    seconds = 0.0
    for number in numbers:
        seconds = seconds * 60 + number
    return seconds


def _clock_to_whole_seconds(value: Any) -> Any:
    seconds = clock_to_seconds(value)
    return round(seconds) if isinstance(seconds, float) else seconds


# Position inside a video file, in seconds (up to 24 hours). Decimals are kept.
OptVideoTime = Annotated[Annotated[float, Field(ge=0, le=86_400)] | None, BeforeValidator(clock_to_seconds)]
# The scoreboard clock, in whole seconds (up to 150 minutes, enough for extra time).
OptMatchClock = Annotated[Annotated[int, Field(ge=0, le=9_000)] | None, BeforeValidator(_clock_to_whole_seconds)]

# Required text: must contain something other than spaces.
RequiredText = Annotated[str, BeforeValidator(_strip), Field(min_length=1)]

def _utc_text(value: datetime) -> str:
    """ "2026-10-09T21:45:04Z". Accepts a value with or without a timezone attached."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec="seconds") + "Z"


# Stored as UTC without a timezone (see models/common.py); sent with a "Z" so
# the browser knows it is UTC and can show your local time.
UtcDateTime = Annotated[datetime, PlainSerializer(_utc_text, return_type=str)]


class InputSchema(BaseModel):
    """Base for request bodies. Unknown fields are refused, which catches typos early."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OutputSchema(BaseModel):
    """Base for responses. Can be built straight from a database object."""

    model_config = ConfigDict(from_attributes=True)


class NamedBrief(OutputSchema):
    """The short form of a team, competition or season inside another record."""

    id: int
    name: str


def http_url(value: str | None) -> str | None:
    """Accept only ordinary web links. Refuses things like javascript: or file: addresses."""
    if value is None:
        return None
    if not value.lower().startswith(("http://", "https://")) or any(ch.isspace() for ch in value):
        raise ValueError("must be a web link starting with http:// or https://")
    return value


def finite(value: float) -> float:
    """Refuse NaN and infinity, which are numbers Python accepts but geometry cannot use."""
    if not math.isfinite(value):
        raise ValueError("must be an ordinary number")
    return value
