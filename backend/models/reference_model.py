"""Reference data: teams, competitions and seasons.

Small lists that players and matches point at. A row here cannot be deleted
while something still points at it (the foreign keys elsewhere say RESTRICT),
so a match can never end up referring to a team that no longer exists.

collation="NOCASE" makes SQLite compare these names ignoring upper/lower case,
so "inter" and "Inter" count as the same team. (It is a SQLite feature.)
"""
from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from models.common import TimestampMixin


class Team(Base, TimestampMixin):
    __tablename__ = "teams"
    __table_args__ = (CheckConstraint("team_type IN ('club', 'national')", name="team_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120, collation="NOCASE"), unique=True)
    team_type: Mapped[str] = mapped_column(String(20), default="club")
    country: Mapped[str | None] = mapped_column(String(80))


class Competition(Base, TimestampMixin):
    __tablename__ = "competitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120, collation="NOCASE"), unique=True)
    country: Mapped[str | None] = mapped_column(String(80))


class Season(Base, TimestampMixin):
    """A season label such as "2025/26". Sorted by name, which works for that format."""

    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40, collation="NOCASE"), unique=True)
