"""Pattern reports: counting your observations in different ways.

FOUR KINDS OF INFORMATION, KEPT APART
-------------------------------------
    recorded facts          what you entered: an observation, a position, an outcome
    calculated statistics   THIS FILE: counts and shares worked out from those records
    your interpretations    the notes and assessments you wrote
    AI hypotheses           optional, clearly labelled, never mixed in here (services/ai/)

THE RULES THIS FILE FOLLOWS
---------------------------
* Everything is deterministic: the same records always give the same numbers.
* Every number comes with the ids of the observations it counts, so a figure
  such as "15 diagonal runs" can be opened as the 15 records behind it.
* "Not recorded" is its own group. It is never dropped and never counted as
  something else.
* Every answer carries `limitations` in plain words: how small the sample is,
  that the counts reflect what you chose to record, and that things happening
  together does not show that one caused the other.
* Nothing here judges. No "pattern detected", no "better player".
"""
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

import vocabulary
from errors import Invalid
from models import MatchAppearance, Observation, Player, PlayerStatistic, ScoutingAssessment, STAT_FIELDS
from services import geometry, observation_service, snapshot_service
from services.common import get_or_404
from services.observation_service import ObservationFilters

# Below this many observations, a group is marked as too small to read much into.
SMALL_SAMPLE = 5
# Per-90 figures from fewer minutes than this (five full matches) swing wildly.
FEW_MINUTES = 450

ALWAYS = "These are counts of what you chose to record, not of everything that happened in the matches."
NOT_CAUSE = ("Two things appearing together does not show that one caused the other. "
             "A movement that is often followed by a shot may simply be attempted in good positions.")


@dataclass
class Group:
    """One value of the thing being grouped by, e.g. the movement "Diagonal run"."""

    key: str
    label: str
    filter: dict | None = None  # extra filter that selects exactly this group on the Observations page
    recorded: bool = True  # False for a "not recorded / not known" group


def _unknown(reason_key: str, label: str) -> Group:
    """A group for observations where the value is missing. Each reason is its own group."""
    return Group(f"?{reason_key}", label, recorded=False)


def _primary_player(observation: Observation) -> Player | None:
    players = observation.players  # primary first (see Observation.players)
    return players[0] if players else None


def _recorded_movement_points(observation: Observation):
    """(start, end, pitch size) of the run this observation is about, from its diagram; or None."""
    for snapshot in observation.snapshots:
        arrow = snapshot_service.recorded_movement(snapshot)
        if arrow is not None:
            start, end = tuple(arrow.points[0]), tuple(arrow.points[1])
            return start, end, (snapshot.pitch_length_m, snapshot.pitch_width_m)
    return None


def _zone_label(point, pitch_size) -> str:
    zone = geometry.pitch_zone(point, *pitch_size)
    if not zone["on_pitch"]:
        return "Off the pitch"
    return f"{zone['third'].capitalize()}, {zone['lane']}"


class _Context:
    """Facts looked up once for a whole report: which side each player was on in each match."""

    def __init__(self, db: Session, observations: list[Observation]):
        match_ids = {observation.match_id for observation in observations if observation.match_id is not None}
        self.side: dict[tuple[int, int], int] = {}
        if match_ids:
            rows = db.execute(select(MatchAppearance.match_id, MatchAppearance.player_id, MatchAppearance.team_id)
                              .where(MatchAppearance.match_id.in_(match_ids))).all()
            self.side = {(match_id, player_id): team_id for match_id, player_id, team_id in rows}

    def opponent(self, observation: Observation) -> Group:
        """The team the studied player was playing AGAINST in this observation's match."""
        match, player = observation.match, _primary_player(observation)
        if match is None or player is None:
            return _unknown("no-match-or-player", "Opponent not known (no match or no player)")
        # Which side was the player on? The lineup says so; failing that, their current club if it played.
        team_id = self.side.get((match.id, player.id))
        if team_id is None and player.current_team_id in (match.home_team_id, match.away_team_id):
            team_id = player.current_team_id
        if team_id == match.home_team_id:
            return Group(f"team-{match.away_team_id}", match.away_team.name)
        if team_id == match.away_team_id:
            return Group(f"team-{match.home_team_id}", match.home_team.name)
        return _unknown("not-in-lineup", "Opponent not known (the player is not in the match lineup)")


def _text_group(field: str):
    def group_of(observation: Observation, _context) -> Group:
        value = getattr(observation, field)
        return Group(value, value, {field: value}) if value else _unknown("empty", "Not recorded")
    return group_of


def _player_group(observation: Observation, _context) -> Group:
    player = _primary_player(observation)
    if player is None:
        return _unknown("no-player", "No player")
    return Group(f"player-{player.id}", player.full_name, {"player_id": player.id})


def _match_group(observation: Observation, _context) -> Group:
    match = observation.match
    if match is None:
        return _unknown("no-match", "Not tied to a match")
    when = f" ({match.match_date.isoformat()})" if match.match_date else ""
    return Group(f"match-{match.id}", f"{match.title}{when}", {"match_id": match.id})


def _competition_group(observation: Observation, _context) -> Group:
    competition = observation.match.competition if observation.match else None
    if competition is None:
        return _unknown("no-competition", "Competition not recorded")
    return Group(f"competition-{competition.id}", competition.name, {"competition_id": competition.id})


def _season_group(observation: Observation, _context) -> Group:
    season = observation.match.season if observation.match else None
    if season is None:
        return _unknown("no-season", "Season not recorded")
    return Group(f"season-{season.id}", season.name, {"season_id": season.id})


def _zone_group(which: int):
    def group_of(observation: Observation, _context) -> Group:
        movement = _recorded_movement_points(observation)
        if movement is None:
            return _unknown("no-movement", "No recorded movement on a pitch diagram")
        label = _zone_label(movement[which], movement[2])
        return Group(label, label)
    return group_of


def _direction_group(observation: Observation, _context) -> Group:
    movement = _recorded_movement_points(observation)
    if movement is None:
        return _unknown("no-movement", "No recorded movement on a pitch diagram")
    words = geometry.describe_direction(geometry.direction_degrees(movement[0], movement[1]))
    if words is None:
        return _unknown("no-length", "Movement with no length")
    return Group(words, words.capitalize())


# What observations can be grouped by: name -> (heading, how to find an observation's group).
DIMENSIONS = {
    "category": ("What it shows", _text_group("category")),
    "movement_category": ("Movement", _text_group("movement_category")),
    "outcome": ("Outcome", _text_group("outcome")),
    "defensive_shape": ("Defensive shape faced", _text_group("defensive_shape")),
    "confidence": ("How sure you were", _text_group("confidence")),
    "player": ("Studied player", _player_group),
    "match": ("Match", _match_group),
    "opponent": ("Opponent", lambda observation, context: context.opponent(observation)),
    "competition": ("Competition", _competition_group),
    "season": ("Season", _season_group),
    "zone_start": ("Where the movement started", _zone_group(0)),
    "zone_end": ("Where the movement ended", _zone_group(1)),
    "direction": ("Direction of the movement", _direction_group),
}
_FROM_DIAGRAMS = {"zone_start", "zone_end", "direction"}


def _dimension(name: str):
    if name not in DIMENSIONS:
        raise Invalid(f"Cannot group by '{name}'. Choose one of: {', '.join(DIMENSIONS)}.")
    return DIMENSIONS[name]


def _sample_limitations(observations: list[Observation]) -> list[str]:
    notes = [ALWAYS]
    total = len(observations)
    matches = len({observation.match_id for observation in observations if observation.match_id is not None})
    if total == 0:
        notes.append("No observations match these filters, so there is nothing to count.")
    elif total < SMALL_SAMPLE:
        notes.append(f"Only {total} observation{'s' if total != 1 else ''} match. "
                     "That is far too few to call anything a pattern.")
    if total and matches < 3:
        notes.append(f"They come from {matches} match{'es' if matches != 1 else ''}. "
                     "A habit across matches needs more matches than that.")
    return notes


def _cell(observations: list[Observation]) -> dict:
    return {"count": len(observations), "observation_ids": [observation.id for observation in observations]}


def patterns(db: Session, filters: ObservationFilters, group_by: str) -> dict:
    """Count the matching observations per value of one dimension, largest group first."""
    heading, group_of = _dimension(group_by)
    observations = observation_service.all_matching(db, filters)
    context = _Context(db, observations)

    buckets: dict[str, list[Observation]] = defaultdict(list)
    described: dict[str, Group] = {}
    for observation in observations:
        group = group_of(observation, context)
        buckets[group.key].append(observation)
        described.setdefault(group.key, group)

    total = len(observations)
    groups = []
    # Largest first; "not recorded" groups always last.
    for key in sorted(buckets, key=lambda k: (not described[k].recorded, -len(buckets[k]), described[k].label)):
        members = buckets[key]
        groups.append({
            "key": key, "label": described[key].label, "recorded": described[key].recorded,
            **_cell(members),
            "share": len(members) / total if total else 0.0,
            "matches": len({m.match_id for m in members if m.match_id is not None}),
            "small_sample": len(members) < SMALL_SAMPLE,
            "filter": described[key].filter,
        })

    limitations = _sample_limitations(observations)
    missing = sum(len(members) for key, members in buckets.items() if not described[key].recorded)
    if missing and total:
        limitations.append(f"{missing} of {total} observations have nothing recorded for this and are listed "
                           "separately. They are not counted as any other value.")
    if group_by in _FROM_DIAGRAMS:
        limitations.append("Positions and directions come from pitch diagrams you drew by eye, so they are "
                           "estimates, and only observations with a recorded movement can be placed.")
    if group_by == "outcome":
        limitations.append(NOT_CAUSE)
    return {"group_by": group_by, "heading": heading, "total": total, "groups": groups, "limitations": limitations}


def crosstab(db: Session, filters: ObservationFilters, rows: str, columns: str) -> dict:
    """Count observations for every combination of two dimensions, e.g. movement by outcome."""
    row_heading, row_of = _dimension(rows)
    column_heading, column_of = _dimension(columns)
    if rows == columns:
        raise Invalid("Choose two different things to compare.")
    observations = observation_service.all_matching(db, filters)
    context = _Context(db, observations)

    cells: dict[tuple, list[Observation]] = defaultdict(list)
    row_groups: dict[str, Group] = {}
    column_groups: dict[str, Group] = {}
    for observation in observations:
        row, column = row_of(observation, context), column_of(observation, context)
        row_groups.setdefault(row.key, row)
        column_groups.setdefault(column.key, column)
        cells[(row.key, column.key)].append(observation)

    def ordered(groups: dict, axis: int) -> list:
        size = defaultdict(int)
        for key, members in cells.items():
            size[key[axis]] += len(members)
        return sorted(groups, key=lambda k: (not groups[k].recorded, -size[k], groups[k].label))

    row_keys, column_keys = ordered(row_groups, 0), ordered(column_groups, 1)
    limitations = _sample_limitations(observations) + [NOT_CAUSE]
    if any(len(members) < SMALL_SAMPLE for members in cells.values()):
        limitations.append(f"Most cells hold fewer than {SMALL_SAMPLE} observations. Differences between such "
                           "small numbers are easily chance.")
    return {
        "rows": rows, "row_heading": row_heading, "columns": columns, "column_heading": column_heading,
        "total": len(observations),
        "row_labels": [row_groups[key].label for key in row_keys],
        "column_labels": [column_groups[key].label for key in column_keys],
        "cells": [[_cell(cells.get((row_key, column_key), [])) for column_key in column_keys] for row_key in row_keys],
        "row_totals": [sum(len(cells.get((row_key, c), [])) for c in column_keys) for row_key in row_keys],
        "column_totals": [sum(len(cells.get((r, column_key), [])) for r in row_keys) for column_key in column_keys],
        "limitations": limitations,
    }


def zone_grid(db: Session, filters: ObservationFilters, point: str = "start") -> dict:
    """Recorded movements on a 3 x 5 grid of the pitch: thirds along the length, lanes across."""
    if point not in ("start", "end"):
        raise Invalid("Choose 'start' or 'end'.")
    observations = observation_service.all_matching(db, filters)
    grid: dict[tuple[str, str], list[Observation]] = defaultdict(list)
    without, off_pitch = [], []
    for observation in observations:
        movement = _recorded_movement_points(observation)
        if movement is None:
            without.append(observation)
            continue
        zone = geometry.pitch_zone(movement[0 if point == "start" else 1], *movement[2])
        if zone["on_pitch"]:
            grid[(zone["third"], zone["lane"])].append(observation)
        else:
            off_pitch.append(observation)

    placed = sum(len(members) for members in grid.values())
    limitations = _sample_limitations(observations) + [
        "Positions come from pitch diagrams you drew by eye, so each one is an estimate.",
        "Diagrams are drawn with the studied team attacking left to right, so 'final third' always means "
        "the third nearest the goal they attack.",
        f"{placed} of {len(observations)} matching observations have a recorded movement on a pitch diagram. "
        "The others cannot be placed and are not shown on the grid.",
    ]
    return {
        "point": point, "total": len(observations),
        "thirds": list(geometry.THIRDS), "lanes": list(geometry.LANES),
        # rows = lanes (left to right across the pitch), columns = thirds (own goal to the goal attacked)
        "cells": [[_cell(grid.get((third, lane), [])) for third in geometry.THIRDS] for lane in geometry.LANES],
        "placed": placed, "without_position": _cell(without), "off_pitch": _cell(off_pitch),
        "limitations": limitations,
    }


# ── Comparing players ────────────────────────────────────────────────────────
def _rate(lines: list[PlayerStatistic], part: str, whole: str) -> dict:
    """part / whole using only stat lines where BOTH numbers are recorded."""
    usable = [line for line in lines if getattr(line, part) is not None and getattr(line, whole) is not None]
    total_whole = sum(getattr(line, whole) for line in usable)
    if not usable or total_whole == 0:
        return {"value": None, "from": None}
    total_part = sum(getattr(line, part) for line in usable)
    return {"value": total_part / total_whole, "from": f"{total_part} of {total_whole}"}


def _player_numbers(db: Session, player: Player, basis: str, season_id: int | None,
                    competition_id: int | None) -> dict:
    statement = select(PlayerStatistic).where(PlayerStatistic.player_id == player.id, PlayerStatistic.scope == basis)
    lines = list(db.scalars(statement))
    if basis == "season":
        lines = [line for line in lines
                 if (season_id is None or line.season_id == season_id)
                 and (competition_id is None or line.competition_id == competition_id)]
    else:
        lines = [line for line in lines
                 if (season_id is None or line.match.season_id == season_id)
                 and (competition_id is None or line.match.competition_id == competition_id)]

    totals, per_90 = {}, {}
    for field in STAT_FIELDS:
        recorded = [line for line in lines if getattr(line, field) is not None]
        # No line has it -> None ("not recorded"). It is NOT zero.
        totals[field] = sum(getattr(line, field) for line in recorded) if recorded else None
        # Per 90 minutes, using only lines that record BOTH this number and the minutes.
        timed = [line for line in recorded if line.minutes_played]
        minutes = sum(line.minutes_played for line in timed)
        per_90[field] = (sum(getattr(line, field) for line in timed) / minutes * 90
                         if minutes and field not in ("appearances", "minutes_played") else None)

    latest = db.scalars(select(ScoutingAssessment).where(ScoutingAssessment.player_id == player.id)
                        .order_by(ScoutingAssessment.assessed_on.desc(), ScoutingAssessment.id.desc())).first()
    return {
        "player": {"id": player.id, "full_name": player.full_name, "primary_position": player.primary_position},
        "position_group": vocabulary.POSITION_GROUPS.get(player.primary_position or ""),
        "stat_lines": len(lines),
        "covers": sorted({line.context for line in lines}),
        "sources": sorted({line.source for line in lines}),
        "totals": totals,
        "per_90": per_90,
        "rates": {
            "shot_accuracy": _rate(lines, "shots_on_target", "shots"),
            "pass_completion": _rate(lines, "passes_completed", "passes_attempted"),
            "duel_success": _rate(lines, "duels_won", "duels_contested"),
        },
        # Your opinion, kept apart from the measured numbers above.
        "latest_assessment": None if latest is None else {
            "id": latest.id, "assessed_on": latest.assessed_on,
            "ratings": {rating.attribute: rating.rating for rating in latest.ratings},
        },
    }


def compare_players(db: Session, player_ids: list[int], basis: str = "season",
                    season_id: int | None = None, competition_id: int | None = None) -> dict:
    """Put players' recorded numbers side by side, with everything that makes the comparison shaky.

    It never names a winner. A bigger number is not a better player.
    """
    if basis not in ("season", "match"):
        raise Invalid("Compare either 'season' stat lines or 'match' stat lines.")
    if len(player_ids) < 2:
        raise Invalid("Choose at least two players to compare.")
    if len(player_ids) != len(set(player_ids)):
        raise Invalid("A player is listed twice.")
    players = [get_or_404(db, Player, player_id, "Player") for player_id in player_ids]
    rows = [_player_numbers(db, player, basis, season_id, competition_id) for player in players]

    limitations = ["A bigger number does not make a better player. Role, team, opposition and luck all shape "
                   "these figures, and none of that is visible in a total."]
    groups = {row["position_group"] for row in rows}
    if len(groups) > 1 or None in groups:
        described = ", ".join(f"{row['player']['full_name']} ({row['position_group'] or 'position not recorded'})"
                              for row in rows)
        limitations.append(f"These players do different jobs: {described}. Their numbers answer different questions.")
    for row in rows:
        name, minutes = row["player"]["full_name"], row["totals"]["minutes_played"]
        if row["stat_lines"] == 0:
            limitations.append(f"{name} has no {basis} stat lines for this selection, so there is nothing to compare.")
        elif minutes is None:
            limitations.append(f"{name} has no minutes recorded, so no per-90 figure can be worked out.")
        elif minutes < FEW_MINUTES:
            limitations.append(f"{name} has only {minutes} recorded minutes. Per-90 figures from so little "
                               "playing time swing wildly from match to match.")
    if len({tuple(row["covers"]) for row in rows}) > 1:
        limitations.append("The numbers do not cover the same matches or competitions for each player (see "
                           "'Covers'), so they were not earned against the same opposition.")
    if len({tuple(row["sources"]) for row in rows if row["sources"]}) > 1:
        limitations.append("The numbers come from different sources, which may count the same thing differently.")
    for field in STAT_FIELDS:
        have = [row["totals"][field] is not None for row in rows]
        if any(have) and not all(have):
            missing = ", ".join(row["player"]["full_name"] for row, has in zip(rows, have) if not has)
            limitations.append(f"'{field.replace('_', ' ')}' is not recorded for {missing}. Not recorded is not "
                               "zero, so that row cannot be compared.")
    return {
        "basis": basis, "stat_fields": STAT_FIELDS, "players": rows, "limitations": limitations,
        "rating_scale_note": vocabulary.RATING_SCALE_NOTE,
    }
