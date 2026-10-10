"""Getting your data out of the app, and back in.

THREE WAYS OUT, FOR THREE PURPOSES
----------------------------------
    Backup archive   everything, including frame pictures. For safety copies and
                     for moving to another computer. (services/backup_service.py)

    JSON export      every table with its ids and links, as one readable text
                     file. For keeping your data in an open format, and for
                     loading into a fresh, EMPTY copy of the app.

    CSV export       one spreadsheet-friendly file per kind of record (players,
                     matches, statistics, observations). For Excel or Numbers,
                     and for bringing in records you prepared in a spreadsheet.

IMPORT RULES
------------
* Every row is checked with the same rules as the forms (the same schemas).
* An import is ALL OR NOTHING. If one row is wrong, nothing is saved and you
  get a list saying which row, which column and why. Nothing is skipped quietly.
* `dry_run` checks a file and reports, without saving anything.
* A CSV import only ever ADDS records. It never changes or deletes existing ones.
* A JSON import only goes into an empty database, so it can never overwrite data.
"""
import csv
import io
import json
from datetime import date, datetime

from pydantic import ValidationError
from sqlalchemy import Date, DateTime, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import config
import database
from errors import AppError, Conflict, Invalid
from migrations_runner import current_revision
from models import STAT_FIELDS, Match, Observation, Player, PlayerStatistic
from models.common import utcnow
from schemas.match_schema import MatchIn
from schemas.observation_schema import ObservationIn
from schemas.player_schema import PlayerIn
from schemas.statistic_schema import StatisticIn
from services import match_service, observation_service, player_service, statistic_service
from services.observation_service import ObservationFilters

EXPORT_FORMAT = "football-analyst-export"
EXPORT_VERSION = 1


# ═════════════════════════════ JSON: everything ══════════════════════════════
def _plain(value):
    """A database value as something JSON can hold."""
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds") + "Z"  # stored as UTC (see models/common.py)
    if isinstance(value, date):
        return value.isoformat()
    return value


def export_all(db: Session) -> dict:
    """Every table, row by row, with ids. Tables are in dependency order (parents first)."""
    tables = {}
    for table in database.Base.metadata.sorted_tables:
        rows = db.execute(select(table).order_by(*table.primary_key.columns)).mappings().all()
        tables[table.name] = [{column: _plain(value) for column, value in row.items()} for row in rows]
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": _plain(utcnow()),
        "schema_revision": current_revision(),
        "note": "Frame pictures are files and are not inside this export; the backup archive has them. "
                "Timestamps ending in Z are UTC. Pitch positions are metres; frame positions are 0-1 fractions.",
        "tables": tables,
    }


def _typed(table, row: dict) -> dict:
    """Turn the text dates of an export back into date objects, column by column."""
    typed = {}
    for name, value in row.items():
        if name not in table.columns:
            raise Invalid(f"The export has a column '{name}' in '{table.name}' that this version does not know.")
        column_type = table.columns[name].type
        if value is not None and isinstance(column_type, DateTime):
            value = datetime.fromisoformat(str(value).removesuffix("Z"))
        elif value is not None and isinstance(column_type, Date):
            value = date.fromisoformat(str(value))
        typed[name] = value
    return typed


def import_all(db: Session, payload: dict, dry_run: bool = False) -> dict:
    """Load a JSON export into an EMPTY database, keeping every id and link."""
    if not isinstance(payload, dict) or payload.get("format") != EXPORT_FORMAT:
        raise Invalid("This is not a Football Analyst JSON export.")
    if payload.get("version") != EXPORT_VERSION:
        raise Invalid(f"This export is version {payload.get('version')}; this app reads version {EXPORT_VERSION}.")
    if payload.get("schema_revision") != current_revision():
        raise Invalid("This export was made by a different version of the app's database "
                      f"({payload.get('schema_revision')}, this one is {current_revision()}). "
                      "Use a backup archive to move data between versions.")
    exported = payload.get("tables")
    known = {table.name: table for table in database.Base.metadata.sorted_tables}
    if not isinstance(exported, dict) or set(exported) - set(known):
        raise Invalid("The export's list of tables does not match this app.")

    occupied = [name for name, table in known.items()
                if db.scalar(select(func.count()).select_from(table))]
    if occupied:
        raise Conflict(
            "This database already contains data, and a full import never overwrites anything. Import into an "
            "empty copy of the app instead: start it with a new, empty data folder (FOOTBALL_DATA_DIR).",
            tables_with_data=occupied,
        )

    counts = {}
    try:
        for name, table in known.items():  # parents before children, so every link has its target
            rows = [_typed(table, row) for row in exported.get(name, [])]
            if rows:
                db.execute(table.insert(), rows)
            counts[name] = len(rows)
        # A diagram may name a picture file that is not on this computer. Say so rather than show a broken picture.
        snapshots = known["tactical_snapshots"]
        missing_pictures = 0
        for snapshot_id, file_name in db.execute(
                select(snapshots.c.id, snapshots.c.frame_image_path).where(snapshots.c.frame_image_path.is_not(None))):
            if not (config.FRAMES_DIR / file_name).is_file():
                db.execute(snapshots.update().where(snapshots.c.id == snapshot_id)
                           .values(frame_image_path=None, frame_source=None))
                missing_pictures += 1
        if dry_run:
            db.rollback()
        else:
            db.commit()
    except IntegrityError as error:
        db.rollback()
        raise Invalid("The export is inconsistent (a record points at something that is not in the file, or an "
                      f"entry appears twice). Nothing was imported. Detail: {error.orig}") from None
    except (ValueError, TypeError) as error:
        db.rollback()
        raise Invalid(f"The export contains a value that cannot be read: {error}. Nothing was imported.") from None
    return {"dry_run": dry_run, "saved": not dry_run, "rows": counts, "total": sum(counts.values()),
            "pictures_missing": missing_pictures}


# ═════════════════════════════ CSV: one kind of record ═══════════════════════
def _cell(value) -> str:
    """A value as CSV text. Text starting with = + or @ gets a leading ' so a
    spreadsheet shows it as text instead of running it as a formula."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return "; ".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False) if value else ""
    text = str(_plain(value))
    return f"'{text}" if text[:1] in ("=", "+", "@") else text


def _csv_text(columns: list[str], rows: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_cell(row.get(column)) for column in columns])
    return "﻿" + buffer.getvalue()  # the leading mark makes Excel read accents correctly


def _clock(seconds: float | None) -> str | None:
    """612.5 -> "10:12.5": a position in a video, written so a person can read it."""
    if seconds is None:
        return None
    whole, fraction = divmod(round(seconds * 1000), 1000)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    text = f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
    return f"{text}.{fraction:03d}".rstrip("0") if fraction else text


PLAYER_COLUMNS = ["id", "full_name", "date_of_birth", "nationality", "height_cm", "preferred_foot", "primary_position",
                  "secondary_positions", "current_team", "national_team", "shirt_number", "photo_url", "notes"]
MATCH_COLUMNS = ["id", "match_date", "home_team", "away_team", "competition", "season", "venue", "home_score",
                 "away_score", "home_formation", "away_formation", "notes"]
STATISTIC_COLUMNS = ["id", "player_id", "player_name", "scope", "match_id", "season", "competition", "team",
                     *STAT_FIELDS, "extra_metrics", "source", "source_url", "notes"]
OBSERVATION_COLUMNS = ["id", "player_ids", "player_names", "primary_player_id", "match_id", "match", "match_date",
                       "video_reference_id", "video_time", "match_clock", "category", "movement_category", "outcome",
                       "tactical_situation", "defensive_shape", "movement_trigger", "intended_space", "notes",
                       "evidence", "confidence", "diagram_count", "created_at", "updated_at"]


def _name(row) -> str | None:
    return row.name if row is not None else None


def export_csv(db: Session, entity: str, filters: ObservationFilters | None = None) -> str:
    if entity == "players":
        rows = [{**{c: getattr(p, c) for c in PLAYER_COLUMNS if hasattr(p, c)},
                 "current_team": _name(p.current_team), "national_team": _name(p.national_team)}
                for p in db.scalars(select(Player).order_by(Player.id))]
        return _csv_text(PLAYER_COLUMNS, rows)
    if entity == "matches":
        rows = [{**{c: getattr(m, c) for c in MATCH_COLUMNS if hasattr(m, c)},
                 "home_team": m.home_team.name, "away_team": m.away_team.name,
                 "competition": _name(m.competition), "season": _name(m.season)}
                for m in db.scalars(select(Match).order_by(Match.id))]
        return _csv_text(MATCH_COLUMNS, rows)
    if entity == "statistics":
        players = {p.id: p.full_name for p in db.scalars(select(Player))}
        rows = [{**{c: getattr(s, c) for c in STATISTIC_COLUMNS if hasattr(s, c)},
                 "player_name": players[s.player_id], "season": _name(s.season),
                 "competition": _name(s.competition), "team": _name(s.team)}
                for s in db.scalars(select(PlayerStatistic).order_by(PlayerStatistic.id))]
        return _csv_text(STATISTIC_COLUMNS, rows)
    if entity == "observations":
        rows = []
        for o in observation_service.all_matching(db, filters or ObservationFilters()):
            players = o.players
            rows.append({
                **{c: getattr(o, c) for c in OBSERVATION_COLUMNS if hasattr(o, c)},
                "player_ids": [p.id for p in players], "player_names": [p.full_name for p in players],
                "primary_player_id": players[0].id if players else None,
                "match": o.match.title if o.match else None,
                "match_date": o.match.match_date if o.match else None,
                "video_time": _clock(o.video_time_seconds), "match_clock": _clock(o.match_clock_seconds),
                "diagram_count": len(o.snapshots),
            })
        return _csv_text(OBSERVATION_COLUMNS, rows)
    raise Invalid("Choose one of: players, matches, statistics, observations.")


# ── CSV import ───────────────────────────────────────────────────────────────
def _split(text: str | None) -> list[str]:
    return [part.strip() for part in (text or "").replace(",", ";").split(";") if part.strip()]


def _whole_numbers(text: str | None, column: str) -> list[int]:
    try:
        return [int(part) for part in _split(text)]
    except ValueError:
        raise Invalid(f"{column} must be whole numbers separated by ;") from None


def _player_row(db: Session, row: dict) -> None:
    payload = {name: row.get(name) for name in PLAYER_COLUMNS if name != "id"}
    payload["secondary_positions"] = _split(row.get("secondary_positions"))
    player_service.create_player(db, PlayerIn.model_validate(payload), commit=False)


def _match_row(db: Session, row: dict) -> None:
    payload = {name: row.get(name) for name in MATCH_COLUMNS if name != "id"}
    match_service.create_match(db, MatchIn.model_validate(payload), commit=False)


def _find_player(db: Session, row: dict) -> int:
    if row.get("player_id"):
        return _whole_numbers(row["player_id"], "player_id")[0]
    name = row.get("player_name")
    if not name:
        raise Invalid("Give player_id or player_name.")
    found = list(db.scalars(select(Player.id).where(Player.full_name == name)))
    if len(found) != 1:
        raise Invalid(f"player_name '{name}' matches {len(found)} players; use player_id instead."
                      if found else f"No player is called '{name}'. Import or add the player first.")
    return found[0]


def _statistic_row(db: Session, row: dict) -> None:
    payload = {name: row.get(name) for name in ("scope", "match_id", "season", "competition", "team",
                                                 *STAT_FIELDS, "source", "source_url", "notes")}
    extra = (row.get("extra_metrics") or "").strip()
    try:
        payload["extra_metrics"] = json.loads(extra) if extra else {}
    except json.JSONDecodeError:
        raise Invalid('extra_metrics must look like {"saves": 4}') from None
    statistic_service.create_statistic(db, _find_player(db, row), StatisticIn.model_validate(payload), commit=False)


def _observation_row(db: Session, row: dict) -> None:
    payload = {name: row.get(name) for name in (
        "match_id", "video_reference_id", "category", "movement_category", "outcome", "tactical_situation",
        "defensive_shape", "movement_trigger", "intended_space", "notes", "evidence", "confidence",
        "primary_player_id")}
    if row.get("player_ids"):
        payload["player_ids"] = _whole_numbers(row["player_ids"], "player_ids")
    else:
        payload["player_ids"] = []
        for name in _split(row.get("player_names")):
            payload["player_ids"].append(_find_player(db, {"player_name": name}))
    payload["video_time_seconds"] = row.get("video_time") or row.get("video_time_seconds")
    payload["match_clock_seconds"] = row.get("match_clock") or row.get("match_clock_seconds")
    observation_service.add_observation(db, ObservationIn.model_validate(payload))


# entity -> (how to save one row, columns it reads, columns that may be present but are ignored)
_IMPORTERS = {
    "players": (_player_row, set(PLAYER_COLUMNS) - {"id"}, {"id", "age", "created_at", "updated_at"}),
    "matches": (_match_row, set(MATCH_COLUMNS) - {"id"}, {"id", "title", "created_at", "updated_at"}),
    "statistics": (_statistic_row, set(STATISTIC_COLUMNS) - {"id"}, {"id", "context", "created_at", "updated_at"}),
    "observations": (_observation_row,
                     {"player_ids", "player_names", "primary_player_id", "match_id", "video_reference_id",
                      "video_time", "video_time_seconds", "match_clock", "match_clock_seconds", "category",
                      "movement_category", "outcome", "tactical_situation", "defensive_shape", "movement_trigger",
                      "intended_space", "notes", "evidence", "confidence"},
                     {"id", "match", "match_date", "diagram_count", "created_at", "updated_at"}),
}


def _unquote(value: str | None) -> str | None:
    """Undo the leading ' that the export puts in front of text starting with = + or @."""
    if value and value[0] == "'" and value[1:2] in ("=", "+", "@"):
        return value[1:]
    return value


def import_csv(db: Session, entity: str, text: str, dry_run: bool = False) -> dict:
    """Add the rows of a CSV file. All of them, or (if any row is wrong) none of them."""
    if entity not in _IMPORTERS:
        raise Invalid("Choose one of: players, matches, statistics, observations.")
    save_row, readable, ignorable = _IMPORTERS[entity]

    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    columns = [(name or "").strip() for name in (reader.fieldnames or [])]
    if not columns or not any(columns):
        raise Invalid("The file is empty or has no header row. The first line must name the columns.")
    unknown = [name for name in columns if name not in readable | ignorable]
    if unknown:
        raise Invalid(f"Unknown column(s): {', '.join(unknown)}. Columns this import reads: "
                      f"{', '.join(sorted(readable))}.")
    ignored = [name for name in columns if name in ignorable]

    errors: list[dict] = []
    rows = 0
    try:
        # Line 1 is the header, so the first data row is line 2: the numbers match what a spreadsheet shows.
        for line, raw in enumerate(reader, start=2):
            # An empty cell becomes None: "not known", exactly as an empty form field does.
            row = {(name or "").strip(): _unquote((value or "").strip()) or None for name, value in raw.items() if name}
            if not any(row.values()):
                continue  # a completely empty line
            rows += 1
            if None in raw:  # more cells than columns
                errors.append({"row": line, "column": None, "message": "This row has more cells than the header."})
                continue
            try:
                save_row(db, row)
            except ValidationError as error:
                for problem in error.errors():
                    errors.append({"row": line, "column": ".".join(str(part) for part in problem["loc"]) or None,
                                   "message": problem["msg"].removeprefix("Value error, ")})
            except AppError as error:
                errors.append({"row": line, "column": None, "message": error.detail})
        if errors or dry_run:
            db.rollback()
        else:
            db.commit()
    except IntegrityError as error:
        db.rollback()
        errors.append({"row": None, "column": None,
                       "message": f"The database refused the data (a duplicate or a broken link): {error.orig}"})

    saved = not errors and not dry_run
    return {
        "entity": entity, "dry_run": dry_run, "rows": rows, "saved": saved,
        "created": rows if saved else 0,
        "would_create": rows if dry_run and not errors else 0,
        "ignored_columns": ignored,  # present in the file but export-only, so not read
        "errors": errors,
    }
