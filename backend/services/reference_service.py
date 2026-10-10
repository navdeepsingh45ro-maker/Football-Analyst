"""Teams, competitions and seasons.

The forms let you type a name instead of picking from a list. get_or_create_*
turns that name into a row: the existing one if the name is already known
(ignoring upper/lower case), otherwise a new one. They only flush, never commit,
so the new team is saved or discarded together with the player or match that
caused it.
"""
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from errors import Conflict
from models import Competition, Match, MatchAppearance, Player, PlayerStatistic, Season, Team
from services.common import get_or_404


def _get_or_create(db: Session, model, name: str | None, **defaults):
    if name is None:
        return None
    # The name columns use NOCASE, so == already ignores upper/lower case.
    existing = db.scalar(select(model).where(model.name == name))
    if existing is not None:
        return existing
    row = model(name=name, **defaults)
    db.add(row)
    db.flush()  # sends the INSERT so row.id exists, but stays inside the current transaction
    return row


def get_or_create_team(db: Session, name: str | None, team_type: str = "club") -> Team | None:
    return _get_or_create(db, Team, name, team_type=team_type)


def get_or_create_competition(db: Session, name: str | None) -> Competition | None:
    return _get_or_create(db, Competition, name)


def get_or_create_season(db: Session, name: str | None) -> Season | None:
    return _get_or_create(db, Season, name)


def _count(db: Session, statement) -> int:
    return db.scalar(select(func.count()).select_from(statement.subquery())) or 0


def usage(db: Session, kind: str, record_id: int) -> dict[str, int]:
    """How many records still point at a team, competition or season."""
    if kind == "team":
        return {
            "players": _count(db, select(Player.id).where(
                or_(Player.current_team_id == record_id, Player.national_team_id == record_id))),
            "matches": _count(db, select(Match.id).where(
                or_(Match.home_team_id == record_id, Match.away_team_id == record_id))),
            "appearances": _count(db, select(MatchAppearance.id).where(MatchAppearance.team_id == record_id)),
            "statistics": _count(db, select(PlayerStatistic.id).where(PlayerStatistic.team_id == record_id)),
        }
    column = {"competition": "competition_id", "season": "season_id"}[kind]
    return {
        "matches": _count(db, select(Match.id).where(getattr(Match, column) == record_id)),
        "statistics": _count(db, select(PlayerStatistic.id).where(getattr(PlayerStatistic, column) == record_id)),
    }


_MODELS = {"team": Team, "competition": Competition, "season": Season}


def rename_or_update(db: Session, kind: str, record_id: int, values: dict):
    """Change a team, competition or season. Refuses a name another row already has."""
    model = _MODELS[kind]
    row = get_or_404(db, model, record_id, kind.capitalize())
    clash = db.scalar(select(model).where(model.name == values["name"], model.id != record_id))
    if clash is not None:
        raise Conflict(f"There is already a {kind} called {clash.name}")
    for field, value in values.items():
        setattr(row, field, value)
    db.commit()
    return row


def create(db: Session, kind: str, values: dict):
    model = _MODELS[kind]
    clash = db.scalar(select(model).where(model.name == values["name"]))
    if clash is not None:
        raise Conflict(f"There is already a {kind} called {clash.name}")
    row = model(**values)
    db.add(row)
    db.commit()
    return row


def delete(db: Session, kind: str, record_id: int) -> None:
    """Delete a team, competition or season, but only when nothing uses it any more."""
    row = get_or_404(db, _MODELS[kind], record_id, kind.capitalize())
    in_use = {what: count for what, count in usage(db, kind, record_id).items() if count}
    if in_use:
        described = ", ".join(f"{count} {what}" for what, count in in_use.items())
        raise Conflict(f"{row.name} is still used by {described}, so it cannot be deleted.", in_use=in_use)
    db.delete(row)
    db.commit()
