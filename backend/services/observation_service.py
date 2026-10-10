"""Observations: saving them, editing them in place, and finding them again.

`ObservationFilters` + `apply_filters` are shared with the pattern reports
(services/analytics_service.py). That guarantees a number in a report and the
list you get when you click on it are produced by the very same filter.
"""
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

import vocabulary
from errors import Invalid, NotFound
from models import Match, Observation, ObservationPlayer, Player, TacticalSnapshot, VideoReference
from schemas.observation_schema import ObservationCreate, ObservationIn
from services import snapshot_service
from services.common import get_or_404, like_pattern

# The plain columns copied straight from the form.
_FIELDS = (
    "match_id", "video_reference_id", "video_time_seconds", "match_clock_seconds", "category",
    "movement_category", "outcome", "tactical_situation", "defensive_shape", "movement_trigger",
    "intended_space", "notes", "evidence", "confidence",
)
_SEARCHED = ("notes", "tactical_situation", "movement_trigger", "intended_space", "evidence", "defensive_shape",
             "category", "movement_category", "outcome")


@dataclass
class ObservationFilters:
    """Every way observations can be narrowed down. All optional; they combine with AND."""

    player_id: int | None = None
    match_id: int | None = None
    team_id: int | None = None  # a team that played in the match
    competition_id: int | None = None
    season_id: int | None = None
    position: str | None = None  # primary position of a player in the observation
    category: str | None = None
    movement_category: str | None = None
    outcome: str | None = None
    ended_in_shot_or_chance: bool | None = None
    defensive_shape: str | None = None
    confidence: str | None = None
    date_from: date | None = None  # match date
    date_to: date | None = None
    has_diagram: bool | None = None
    q: str | None = None  # search text
    ids: str | None = None  # exact observations, e.g. "3,7,12": how a report figure links to its records


def _same_text(column, value: str):
    return func.lower(column) == value.strip().lower()


def _parse_ids(text: str) -> list[int]:
    try:
        return [int(part) for part in text.split(",") if part.strip()]
    except ValueError:
        raise Invalid("ids must be whole numbers separated by commas, for example 3,7,12") from None


def apply_filters(statement: Select, filters: ObservationFilters) -> Select:
    """Narrow a query on Observation. Uses sub-queries, so the result has one row per observation."""
    if filters.ids is not None:
        statement = statement.where(Observation.id.in_(_parse_ids(filters.ids)))
    if filters.player_id is not None:
        statement = statement.where(Observation.id.in_(
            select(ObservationPlayer.observation_id).where(ObservationPlayer.player_id == filters.player_id)))
    if filters.position:
        statement = statement.where(Observation.id.in_(
            select(ObservationPlayer.observation_id).join(Player, Player.id == ObservationPlayer.player_id)
            .where(_same_text(Player.primary_position, filters.position))))
    if filters.match_id is not None:
        statement = statement.where(Observation.match_id == filters.match_id)

    # Filters that describe the match. An observation without a match cannot
    # satisfy them, so it is left out whenever one of them is used.
    matches = select(Match.id)
    uses_match = False
    if filters.team_id is not None:
        matches = matches.where(or_(Match.home_team_id == filters.team_id, Match.away_team_id == filters.team_id))
        uses_match = True
    if filters.competition_id is not None:
        matches, uses_match = matches.where(Match.competition_id == filters.competition_id), True
    if filters.season_id is not None:
        matches, uses_match = matches.where(Match.season_id == filters.season_id), True
    if filters.date_from is not None:
        matches, uses_match = matches.where(Match.match_date >= filters.date_from), True
    if filters.date_to is not None:
        matches, uses_match = matches.where(Match.match_date <= filters.date_to), True
    if uses_match:
        statement = statement.where(Observation.match_id.in_(matches))

    for name in ("category", "movement_category", "outcome", "defensive_shape", "confidence"):
        value = getattr(filters, name)
        if value:
            statement = statement.where(_same_text(getattr(Observation, name), value))
    if filters.ended_in_shot_or_chance is not None:
        in_group = Observation.outcome.in_(vocabulary.SHOT_OR_CHANCE_OUTCOMES)
        statement = statement.where(in_group if filters.ended_in_shot_or_chance
                                    else or_(Observation.outcome.is_(None), ~in_group))
    if filters.has_diagram is not None:
        with_diagram = select(TacticalSnapshot.observation_id).where(TacticalSnapshot.observation_id.is_not(None))
        statement = statement.where(Observation.id.in_(with_diagram) if filters.has_diagram
                                    else Observation.id.not_in(with_diagram))
    if filters.q and filters.q.strip():
        pattern = like_pattern(filters.q.strip())
        named_players = (select(ObservationPlayer.observation_id)
                         .join(Player, Player.id == ObservationPlayer.player_id)
                         .where(Player.full_name.like(pattern, escape="\\")))
        statement = statement.where(or_(
            *[getattr(Observation, name).like(pattern, escape="\\") for name in _SEARCHED],
            Observation.id.in_(named_players),
        ))
    return statement


def _ordered(statement: Select) -> Select:
    """Most recent match first, then in the order things happened in the video."""
    return (statement.outerjoin(Match, Observation.match_id == Match.id)
            .order_by(Match.match_date.desc().nulls_last(), Observation.match_id.desc().nulls_last(),
                      Observation.video_time_seconds.asc().nulls_last(), Observation.id.asc()))


def search(db: Session, filters: ObservationFilters, limit: int = 100, offset: int = 0) -> tuple[int, list[Observation]]:
    """One page of matching observations, plus how many match in total."""
    filtered = apply_filters(select(Observation), filters)
    total = db.scalar(select(func.count()).select_from(filtered.subquery())) or 0
    items = list(db.scalars(_ordered(filtered).limit(limit).offset(offset)))
    return total, items


def all_matching(db: Session, filters: ObservationFilters) -> list[Observation]:
    """Every matching observation (the reports need all of them, not a page)."""
    return list(db.scalars(_ordered(apply_filters(select(Observation), filters))))


def _apply(db: Session, observation: Observation, data: ObservationIn) -> None:
    if data.match_id is not None:
        get_or_404(db, Match, data.match_id, "Match")
    if data.video_reference_id is not None:
        video = get_or_404(db, VideoReference, data.video_reference_id, "Video")
        if video.match_id != data.match_id:
            raise Invalid("That video belongs to a different match.")
    if data.player_ids:
        found = set(db.scalars(select(Player.id).where(Player.id.in_(data.player_ids))))
        missing = [player_id for player_id in data.player_ids if player_id not in found]
        if missing:
            raise NotFound(f"Player {missing[0]} does not exist")

    for name in _FIELDS:
        setattr(observation, name, getattr(data, name))

    # Replace the player links (delete the old rows before inserting the new ones).
    primary = data.primary_player_id or (data.player_ids[0] if data.player_ids else None)
    if observation.player_links:
        observation.player_links.clear()
        db.flush()
    observation.player_links = [
        ObservationPlayer(player_id=player_id, role="primary" if player_id == primary else "involved")
        for player_id in data.player_ids
    ]


def create_observation(db: Session, data: ObservationCreate) -> Observation:
    """Save an observation and, if one was drawn, its diagram. All of it or none of it."""
    observation = Observation()
    db.add(observation)
    with snapshot_service.saving_files(db) as files:
        _apply(db, observation, data)
        if data.snapshot is not None:
            snapshot = TacticalSnapshot()
            observation.snapshots.append(snapshot)
            snapshot_service.apply(db, snapshot, data.snapshot, files)
    return observation


def add_observation(db: Session, data: ObservationIn) -> Observation:
    """Add a written observation (no diagram) WITHOUT committing. Used by the CSV import."""
    observation = Observation()
    db.add(observation)
    _apply(db, observation, data)
    db.flush()
    return observation


def update_observation(db: Session, observation_id: int, data: ObservationIn) -> Observation:
    """Change an observation IN PLACE. Its id stays the same and no copy is made.

    Every field is set from what was sent, including the timestamps: they only
    change if the caller sends different values. Nothing here reads a video.
    """
    observation = get_or_404(db, Observation, observation_id, "Observation")
    _apply(db, observation, data)
    db.commit()
    return observation


def to_out(observation: Observation) -> dict:
    links = sorted(observation.player_links, key=lambda link: (link.role != "primary", link.player.full_name))
    out = {name: getattr(observation, name) for name in _FIELDS if name != "match_id"}
    out.update({
        "id": observation.id,
        "match": observation.match,
        "players": [{"id": link.player.id, "full_name": link.player.full_name,
                     "primary_position": link.player.primary_position, "role": link.role} for link in links],
        "snapshot_ids": [snapshot.id for snapshot in observation.snapshots],
        "created_at": observation.created_at,
        "updated_at": observation.updated_at,
    })
    return out


def to_detail(observation: Observation) -> dict:
    derived = [{"id": note.id, "title": note.title, "kind": "coaching_note"} for note in observation.coaching_notes]
    derived += [{"id": idea.id, "title": idea.title, "kind": "training_idea"} for idea in observation.training_ideas]
    return {
        **to_out(observation),
        "snapshots": [snapshot_service.to_out(snapshot) for snapshot in observation.snapshots],
        "derived": derived,
    }
