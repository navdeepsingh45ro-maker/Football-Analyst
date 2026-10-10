"""Measured statistics: saving stat lines without ever counting something twice."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from errors import Conflict
from models import Match, Player, PlayerStatistic
from schemas.statistic_schema import StatisticIn
from services import reference_service
from services.common import get_or_404


def _columns(db: Session, data: StatisticIn) -> dict:
    """Turn the submitted form into column values, resolving names to ids."""
    values = data.model_dump(exclude={"season", "competition", "team"})
    if data.scope == "match":
        get_or_404(db, Match, data.match_id, "Match")
        values.update(season_id=None, competition_id=None, team_id=None)  # these come from the match
    else:
        season = reference_service.get_or_create_season(db, data.season)
        competition = reference_service.get_or_create_competition(db, data.competition)
        team = reference_service.get_or_create_team(db, data.team)
        values.update(season_id=season.id,
                      competition_id=competition.id if competition else None,
                      team_id=team.id if team else None)
    return values


def _same(column, value):
    """SQL equality that also works for "both unknown" (NULL is never == NULL in SQL)."""
    return column.is_(None) if value is None else column == value


def _refuse_second_line(db: Session, player_id: int, values: dict, exclude_id: int | None = None) -> None:
    statement = select(PlayerStatistic).where(PlayerStatistic.player_id == player_id,
                                              PlayerStatistic.scope == values["scope"])
    if values["scope"] == "match":
        statement = statement.where(PlayerStatistic.match_id == values["match_id"])
    else:
        statement = statement.where(_same(PlayerStatistic.season_id, values["season_id"]),
                                    _same(PlayerStatistic.competition_id, values["competition_id"]),
                                    _same(PlayerStatistic.team_id, values["team_id"]))
    if exclude_id is not None:
        statement = statement.where(PlayerStatistic.id != exclude_id)
    twin = db.scalars(statement).first()
    if twin is not None:
        raise Conflict(
            f"There is already a stat line for {twin.context} (line #{twin.id}). Edit that one instead of adding "
            "a second, so nothing is counted twice.",
            existing_statistic_id=twin.id,
        )


def create_statistic(db: Session, player_id: int, data: StatisticIn, commit: bool = True) -> PlayerStatistic:
    get_or_404(db, Player, player_id, "Player")
    values = _columns(db, data)
    _refuse_second_line(db, player_id, values)
    statistic = PlayerStatistic(player_id=player_id, **values)
    db.add(statistic)
    if commit:
        db.commit()
    else:
        db.flush()  # used by the CSV import, which commits once for the whole file
    return statistic


def update_statistic(db: Session, statistic_id: int, data: StatisticIn) -> PlayerStatistic:
    statistic = get_or_404(db, PlayerStatistic, statistic_id, "Stat line")
    values = _columns(db, data)
    _refuse_second_line(db, statistic.player_id, values, exclude_id=statistic_id)
    for field, value in values.items():
        setattr(statistic, field, value)
    db.commit()
    return statistic


def list_statistics(db: Session, player_id: int) -> list[PlayerStatistic]:
    get_or_404(db, Player, player_id, "Player")
    return list(db.scalars(select(PlayerStatistic).where(PlayerStatistic.player_id == player_id)
                           .order_by(PlayerStatistic.scope.desc(), PlayerStatistic.id.desc())))


def delete_statistic(db: Session, statistic_id: int) -> None:
    db.delete(get_or_404(db, PlayerStatistic, statistic_id, "Stat line"))
    db.commit()
