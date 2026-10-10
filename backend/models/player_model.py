"""Players: the biographical facts about a player.

Every fact except the name may be unknown, and unknown is stored as NULL, never
as a guess. Opinions about the player do NOT live here: they are dated scouting
assessments (assessment_model.py), so changing a player's club or shirt number
never rewrites what you thought of them in the past.
"""
from datetime import date

from sqlalchemy import JSON, CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.common import TimestampMixin
from models.reference_model import Team


class Player(Base, TimestampMixin):
    __tablename__ = "players"
    __table_args__ = (
        # Same name AND same birth date = the same person entered twice. When the
        # birth date is unknown the database cannot tell, so services/player_service.py
        # checks that case and asks before creating a second one.
        UniqueConstraint("full_name", "date_of_birth", name="uq_players_full_name_date_of_birth"),
        CheckConstraint("preferred_foot IS NULL OR preferred_foot IN ('left', 'right', 'both')", name="preferred_foot"),
        CheckConstraint("height_cm IS NULL OR height_cm BETWEEN 120 AND 230", name="height_cm"),
        CheckConstraint("shirt_number IS NULL OR shirt_number BETWEEN 1 AND 99", name="shirt_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(160, collation="NOCASE"), index=True)
    photo_url: Mapped[str | None] = mapped_column(String(500))  # a link to an image, not the image itself
    date_of_birth: Mapped[date | None]
    nationality: Mapped[str | None] = mapped_column(String(80))
    height_cm: Mapped[int | None]
    preferred_foot: Mapped[str | None] = mapped_column(String(10))
    primary_position: Mapped[str | None] = mapped_column(String(20), index=True)
    # A JSON list such as ["RW", "SS"]. Always assign a new list; SQLAlchemy does
    # not notice when a list stored in a JSON column is changed in place.
    secondary_positions: Mapped[list[str]] = mapped_column(JSON, default=list)
    current_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="RESTRICT"), index=True)
    national_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="RESTRICT"))
    shirt_number: Mapped[int | None]
    notes: Mapped[str | None] = mapped_column(Text)

    current_team: Mapped[Team | None] = relationship(foreign_keys=[current_team_id])
    national_team: Mapped[Team | None] = relationship(foreign_keys=[national_team_id])

    @property
    def age(self) -> int | None:
        """Age today, worked out from the birth date. None when the birth date is unknown."""
        if self.date_of_birth is None:
            return None
        today = date.today()
        had_birthday = (today.month, today.day) >= (self.date_of_birth.month, self.date_of_birth.day)
        return today.year - self.date_of_birth.year - (0 if had_birthday else 1)
