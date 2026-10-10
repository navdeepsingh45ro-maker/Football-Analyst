"""Pieces shared by every model.

TIMESTAMP CONVENTION
--------------------
Every created_at / updated_at in the database is a calendar moment in UTC,
stored without a timezone (SQLite has no timezone type). The API adds the "Z"
when it sends them out, and the browser converts to your local time for display.

Do not confuse these with a VIDEO timestamp such as 32:14. That is a position
inside a video and is stored as a plain number of seconds (see observation_model.py).
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column


def utcnow() -> datetime:
    """The current moment in UTC, without tzinfo (see the convention above)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    """Adds created_at and updated_at. updated_at changes whenever the row itself is saved."""

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
