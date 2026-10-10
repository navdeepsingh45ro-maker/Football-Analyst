"""Matches, who played in them, and where the footage is.

    Match ──< MatchAppearance >── Player     (who played, for which side, when they came on/off)
      │
      └────< VideoReference                  (where the footage is: a file path or a link)

Appearances and video references are parts of a match, so they are removed with
it (ON DELETE CASCADE). Players and teams are not: a player or team that still
appears in a match cannot be deleted by accident (ON DELETE RESTRICT).
"""
from datetime import date

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.common import TimestampMixin
from models.player_model import Player
from models.reference_model import Competition, Season, Team


class Match(Base, TimestampMixin):
    __tablename__ = "matches"
    __table_args__ = (
        # Two teams cannot meet twice on the same day, so that would be a duplicate entry.
        UniqueConstraint("home_team_id", "away_team_id", "match_date", name="uq_matches_teams_date"),
        CheckConstraint("home_team_id != away_team_id", name="different_teams"),
        CheckConstraint("home_score IS NULL OR home_score >= 0", name="home_score"),
        CheckConstraint("away_score IS NULL OR away_score >= 0", name="away_score"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="RESTRICT"), index=True)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="RESTRICT"), index=True)
    competition_id: Mapped[int | None] = mapped_column(ForeignKey("competitions.id", ondelete="RESTRICT"), index=True)
    season_id: Mapped[int | None] = mapped_column(ForeignKey("seasons.id", ondelete="RESTRICT"), index=True)
    match_date: Mapped[date | None] = mapped_column(index=True)
    venue: Mapped[str | None] = mapped_column(String(160))
    home_score: Mapped[int | None]  # NULL = unknown, which is different from 0
    away_score: Mapped[int | None]
    home_formation: Mapped[str | None] = mapped_column(String(40))
    away_formation: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text)

    home_team: Mapped[Team] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped[Team] = relationship(foreign_keys=[away_team_id])
    competition: Mapped[Competition | None] = relationship()
    season: Mapped[Season | None] = relationship()
    appearances: Mapped[list["MatchAppearance"]] = relationship(
        back_populates="match", cascade="all, delete-orphan", passive_deletes=True
    )
    videos: Mapped[list["VideoReference"]] = relationship(
        back_populates="match", cascade="all, delete-orphan", passive_deletes=True, order_by="VideoReference.id"
    )

    @property
    def title(self) -> str:
        return f"{self.home_team.name} v {self.away_team.name}"

    def side_of(self, team_id: int | None) -> str | None:
        """ "home" or "away" for one of this match's teams; None for any other team."""
        if team_id == self.home_team_id:
            return "home"
        if team_id == self.away_team_id:
            return "away"
        return None


class MatchAppearance(Base, TimestampMixin):
    """One player taking part in one match.

    Substitutions are recorded here rather than in a separate table:
      starter replaced in the 70th minute  -> is_starter=True,  minute_off=70
      substitute who came on in the 70th   -> is_starter=False, minute_on=70
    """

    __tablename__ = "match_appearances"
    __table_args__ = (
        UniqueConstraint("match_id", "player_id", name="uq_match_appearances_match_player"),
        CheckConstraint("minute_on IS NULL OR minute_on BETWEEN 0 AND 130", name="minute_on"),
        CheckConstraint("minute_off IS NULL OR minute_off BETWEEN 0 AND 130", name="minute_off"),
        CheckConstraint("shirt_number IS NULL OR shirt_number BETWEEN 1 AND 99", name="shirt_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="RESTRICT"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="RESTRICT"))  # the side they played for
    is_starter: Mapped[bool] = mapped_column(default=True)
    shirt_number: Mapped[int | None]
    position: Mapped[str | None] = mapped_column(String(20))  # where they played in THIS match
    minute_on: Mapped[int | None]
    minute_off: Mapped[int | None]

    match: Mapped[Match] = relationship(back_populates="appearances")
    player: Mapped[Player] = relationship()
    team: Mapped[Team] = relationship()

    @property
    def side(self) -> str | None:
        return self.match.side_of(self.team_id)


class VideoReference(Base, TimestampMixin):
    """Where the footage of a match can be found.

    This is a REFERENCE: a path on your disk or a link. The video itself is never
    copied into the app. Whether the app can actually play it depends on `kind`
    (see services/video_service.py), and the API always says which it is.
    """

    __tablename__ = "video_references"
    __table_args__ = (
        CheckConstraint("kind IN ('local_file', 'direct_url', 'youtube', 'external_link')", name="kind"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(120), default="Full match")
    kind: Mapped[str] = mapped_column(String(20))
    location: Mapped[str] = mapped_column(String(1000))  # absolute file path, or URL
    notes: Mapped[str | None] = mapped_column(Text)

    match: Mapped[Match] = relationship(back_populates="videos")
