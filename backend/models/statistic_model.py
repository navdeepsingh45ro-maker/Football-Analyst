"""Measured performance statistics (as opposed to opinions, which are assessments).

One row is one "stat line": a player's numbers for EITHER one match OR one season.

RULES THAT KEEP THE NUMBERS HONEST
----------------------------------
* Every number may be NULL, and NULL means "not recorded". It is never treated
  as 0. A striker with no recorded shots has unknown shots, not zero shots.
* Every line must say where the numbers came from (`source`).
* At most one line per player per match, and one per player per
  season + competition + team. So nothing can be counted twice by mistake.
"""
from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.common import TimestampMixin
from models.match_model import Match
from models.reference_model import Competition, Season, Team

# The countable statistics, in the order they are shown. Used by schemas,
# comparisons and CSV import/export so the list exists in exactly one place.
STAT_FIELDS = [
    "appearances", "minutes_played", "goals", "assists", "shots", "shots_on_target", "chances_created",
    "passes_completed", "passes_attempted", "dribbles_completed", "duels_won", "duels_contested",
]


class PlayerStatistic(Base, TimestampMixin):
    __tablename__ = "player_statistics"
    __table_args__ = (
        CheckConstraint(
            "(scope = 'match' AND match_id IS NOT NULL) OR "
            "(scope = 'season' AND match_id IS NULL AND season_id IS NOT NULL)",
            name="scope_context",
        ),
        # One line per player per match. (The season rule involves columns that can
        # be NULL, which a unique index cannot police, so the service checks it.)
        Index(
            "uq_player_statistics_player_match", "player_id", "match_id",
            unique=True, sqlite_where=text("match_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="RESTRICT"), index=True)
    scope: Mapped[str] = mapped_column(String(10))  # "match" or "season"
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), index=True)
    season_id: Mapped[int | None] = mapped_column(ForeignKey("seasons.id", ondelete="RESTRICT"))
    competition_id: Mapped[int | None] = mapped_column(ForeignKey("competitions.id", ondelete="RESTRICT"))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="RESTRICT"))

    appearances: Mapped[int | None]
    minutes_played: Mapped[int | None]
    goals: Mapped[int | None]
    assists: Mapped[int | None]
    shots: Mapped[int | None]
    shots_on_target: Mapped[int | None]
    chances_created: Mapped[int | None]
    passes_completed: Mapped[int | None]
    passes_attempted: Mapped[int | None]
    dribbles_completed: Mapped[int | None]
    duels_won: Mapped[int | None]
    duels_contested: Mapped[int | None]
    # Anything position-specific, e.g. {"saves": 4, "clearances": 7}. Numbers only.
    extra_metrics: Mapped[dict] = mapped_column(JSON, default=dict)

    source: Mapped[str] = mapped_column(String(200))  # e.g. "Counted myself from the video"
    source_url: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)

    match: Mapped[Match | None] = relationship()
    season: Mapped[Season | None] = relationship()
    competition: Mapped[Competition | None] = relationship()
    team: Mapped[Team | None] = relationship()

    @property
    def context(self) -> str:
        """What these numbers cover, in words: one match, or a season (+ competition, + team)."""
        if self.match is not None:
            when = f" ({self.match.match_date.isoformat()})" if self.match.match_date else ""
            return f"{self.match.title}{when}"
        parts = [self.season.name if self.season else None,
                 self.competition.name if self.competition else None,
                 self.team.name if self.team else None]
        return ", ".join(part for part in parts if part)
