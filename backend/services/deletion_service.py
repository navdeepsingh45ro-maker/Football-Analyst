"""Deleting things: every rule about what disappears with what, in one place.

THE POLICY
----------
Nothing with analysis attached is ever deleted by a single click.

  Player        If the player has assessments, statistics, lineup entries or
                observations, a plain delete is REFUSED and the answer lists how
                many of each exist. Deleting anyway needs cascade=True, which the
                interface only sends after you confirm with those numbers in
                front of you. With cascade, the player's assessments, statistics
                and lineup entries go. An observation about ONLY this player goes
                too (with its diagrams); an observation shared with other players
                stays, minus this player.

  Match         Same idea: refused while it has observations, statistics, lineup
                entries or video links, unless cascade=True.

  Observation   Deleted with its diagrams and their shapes. Coaching notes and
                training ideas that came from it are KEPT; only the link goes.

  Diagram       Deleted with its shapes and its saved frame image.

  Team /        Can only be deleted when nothing uses them (reference_service.delete).
  competition /
  season

Everything for one deletion happens in a single transaction: either all of it is
removed or none of it is. Frame image files are removed only AFTER the database
change has been committed, so a failed delete can never leave a diagram pointing
at a picture that is gone.
"""
import logging
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

import config
from errors import Conflict
from models import (
    Match, MatchAppearance, Observation, ObservationPlayer, Player, PlayerStatistic, ScoutingAssessment,
    TacticalSnapshot, VideoReference,
)
from services.common import get_or_404

logger = logging.getLogger("football")


def remove_frame_files(file_names: list[str]) -> None:
    """Delete saved frame images. Call only after the database commit succeeded."""
    for file_name in file_names:
        # .name drops any folder part, so only files inside the frames folder can be touched.
        path = config.FRAMES_DIR / Path(file_name).name
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            # A leftover picture is harmless; never fail the request over it.
            logger.warning("Could not remove frame image %s: %s", path, error)


def _frame_files_of(db: Session, observation_ids: list[int]) -> list[str]:
    if not observation_ids:
        return []
    return list(db.scalars(select(TacticalSnapshot.frame_image_path).where(
        TacticalSnapshot.observation_id.in_(observation_ids), TacticalSnapshot.frame_image_path.is_not(None))))


def _count(db: Session, model, condition) -> int:
    return db.scalar(select(func.count()).select_from(model).where(condition)) or 0


# ── Observations and diagrams ────────────────────────────────────────────────
def delete_observation(db: Session, observation_id: int) -> None:
    observation = get_or_404(db, Observation, observation_id, "Observation")
    files = _frame_files_of(db, [observation_id])
    db.delete(observation)  # the database removes its player links, diagrams and shapes (ON DELETE CASCADE)
    db.commit()
    remove_frame_files(files)


def delete_snapshot(db: Session, snapshot_id: int) -> None:
    snapshot = get_or_404(db, TacticalSnapshot, snapshot_id, "Diagram")
    files = [snapshot.frame_image_path] if snapshot.frame_image_path else []
    db.delete(snapshot)
    db.commit()
    remove_frame_files(files)


# ── Players ──────────────────────────────────────────────────────────────────
def _observations_about_only(db: Session, player_id: int) -> list[int]:
    """Ids of observations whose ONLY player is this one."""
    theirs = select(ObservationPlayer.observation_id).where(ObservationPlayer.player_id == player_id)
    return list(db.scalars(
        select(ObservationPlayer.observation_id)
        .where(ObservationPlayer.observation_id.in_(theirs))
        .group_by(ObservationPlayer.observation_id)
        .having(func.count() == 1)
    ))


def player_dependencies(db: Session, player_id: int) -> dict[str, int]:
    """What is attached to a player, so the interface can say exactly what a delete would remove."""
    observations = _count(db, ObservationPlayer, ObservationPlayer.player_id == player_id)
    only_theirs = len(_observations_about_only(db, player_id))
    return {
        "assessments": _count(db, ScoutingAssessment, ScoutingAssessment.player_id == player_id),
        "statistics": _count(db, PlayerStatistic, PlayerStatistic.player_id == player_id),
        "appearances": _count(db, MatchAppearance, MatchAppearance.player_id == player_id),
        "observations": observations,
        "observations_deleted": only_theirs,  # about this player alone
        "observations_kept": observations - only_theirs,  # shared with other players
    }


def delete_player(db: Session, player_id: int, cascade: bool = False) -> None:
    player = get_or_404(db, Player, player_id, "Player")
    dependencies = player_dependencies(db, player_id)
    attached = any(dependencies[key] for key in ("assessments", "statistics", "appearances", "observations"))
    if attached and not cascade:
        raise Conflict(
            f"{player.full_name} has records attached, so nothing was deleted. "
            "Confirm to delete the player together with them.",
            dependencies=dependencies,
        )

    solo_observations = _observations_about_only(db, player_id)
    files = _frame_files_of(db, solo_observations)

    # Explicit order: everything that points at the player goes first.
    db.execute(delete(ScoutingAssessment).where(ScoutingAssessment.player_id == player_id))  # ratings cascade
    db.execute(delete(PlayerStatistic).where(PlayerStatistic.player_id == player_id))
    db.execute(delete(MatchAppearance).where(MatchAppearance.player_id == player_id))
    if solo_observations:
        db.execute(delete(Observation).where(Observation.id.in_(solo_observations)))  # diagrams cascade
    db.execute(delete(ObservationPlayer).where(ObservationPlayer.player_id == player_id))
    db.execute(delete(Player).where(Player.id == player_id))
    db.commit()
    remove_frame_files(files)


# ── Matches ──────────────────────────────────────────────────────────────────
def match_dependencies(db: Session, match_id: int) -> dict[str, int]:
    return {
        "observations": _count(db, Observation, Observation.match_id == match_id),
        "statistics": _count(db, PlayerStatistic, PlayerStatistic.match_id == match_id),
        "appearances": _count(db, MatchAppearance, MatchAppearance.match_id == match_id),
        "videos": _count(db, VideoReference, VideoReference.match_id == match_id),
    }


def delete_match(db: Session, match_id: int, cascade: bool = False) -> None:
    match = get_or_404(db, Match, match_id, "Match")
    dependencies = match_dependencies(db, match_id)
    if any(dependencies.values()) and not cascade:
        raise Conflict(
            f"{match.title} has records attached, so nothing was deleted. "
            "Confirm to delete the match together with them.",
            dependencies=dependencies,
        )

    observation_ids = list(db.scalars(select(Observation.id).where(Observation.match_id == match_id)))
    files = _frame_files_of(db, observation_ids)

    db.execute(delete(Observation).where(Observation.match_id == match_id))  # diagrams cascade
    db.execute(delete(Match).where(Match.id == match_id))  # lineups, videos and match stat lines cascade
    db.commit()
    remove_frame_files(files)
