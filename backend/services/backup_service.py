"""Backups of your data, and getting them back.

A backup is ONE zip file holding everything the app stores for you:

    football.db          a consistent copy of the database
    media/frames/...     every saved frame picture
    manifest.json        when it was made, the database version, how many rows per table

EVERY BACKUP IS CHECKED THE MOMENT IT IS MADE
---------------------------------------------
create_backup() does not just write the file and hope. It immediately reopens
the archive (verify_backup): every file's checksum is tested, the database copy
is opened and SQLite's own integrity check is run on it, and its row counts are
compared with what was recorded. The answer says whether that check passed.

GETTING A BACKUP BACK
---------------------
restore_backup() replaces the app's data with a backup. It must only be used
while the server is stopped; the script backend/scripts/restore_backup.py does
it for you. The data being replaced is MOVED ASIDE into a dated folder, never
deleted, so a mistaken restore can itself be undone.
"""
import json
import re
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import config
from errors import Invalid, NotFound

_BACKUP_NAME = re.compile(r"football-backup-\d{8}-\d{6}(-\d+)?\.zip")
_FRAME_MEMBER = re.compile(r"media/frames/[A-Za-z0-9._-]+")


def _open_read_only(path: Path) -> sqlite3.Connection:
    """Open a database file for reading only. It must already exist.

    SQLite takes a "file:" address here, in which characters such as # ? % and
    spaces have special meanings. Path.as_uri() escapes them all. Building the
    address by hand breaks on a folder called "match #1": everything from the #
    on is silently dropped and a DIFFERENT, empty file is opened instead.
    """
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"No database file at {path}")
    return sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)


def copy_sqlite_database(source: Path, destination: Path) -> Path:
    """Copy a SQLite database using SQLite's own backup feature.

    Why not just copy the file? If the app is in the middle of writing, a plain
    file copy can capture a half-written database. SQLite's backup API always
    produces a consistent copy.
    """
    source_connection = _open_read_only(source)
    try:
        destination_connection = sqlite3.connect(destination)
        try:
            source_connection.backup(destination_connection)
        finally:
            destination_connection.close()
    finally:
        source_connection.close()
    return destination


def _inspect_database(path: Path) -> dict:
    """Open a database file read-only: is it sound, which version, how many rows per table."""
    connection = _open_read_only(path)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        names = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        revision = None
        if "alembic_version" in names:
            found = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            revision = found[0] if found else None
        tables = {name: connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                  for name in names if name != "alembic_version"}
    finally:
        connection.close()
    return {"integrity_check": integrity, "schema_revision": revision, "tables": tables}


def create_backup() -> dict:
    """Write a new backup archive into data/backups, verify it, and report what it holds."""
    if not config.DATABASE_FILE.is_file():
        raise Invalid("There is no database to back up yet.")
    config.BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = config.BACKUPS_DIR / f"football-backup-{stamp}.zip"
    extra = 1
    while path.exists():  # two backups in the same second
        extra += 1
        path = config.BACKUPS_DIR / f"football-backup-{stamp}-{extra}.zip"

    with tempfile.TemporaryDirectory() as scratch:
        database_copy = copy_sqlite_database(config.DATABASE_FILE, Path(scratch) / "football.db")
        facts = _inspect_database(database_copy)
        frames = sorted(frame for frame in config.FRAMES_DIR.glob("*") if frame.is_file())
        manifest = {
            "app": "Football Analyst & Coach",
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "schema_revision": facts["schema_revision"],
            "tables": facts["tables"],
            "frames": [frame.name for frame in frames],
        }
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(database_copy, "football.db")
            for frame in frames:
                archive.write(frame, f"media/frames/{frame.name}")
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))

    check = verify_backup(path)
    # The archive agreeing with itself is not enough: it must hold what the LIVE
    # database holds. Count the live rows separately and compare.
    live = _inspect_database(config.DATABASE_FILE)["tables"]
    if check["ok"] and check["tables"] != live:
        check["ok"] = False
        check["problem"] = ("the backup does not hold the same number of rows as the database in use "
                            f"({sum(check['tables'].values())} in the backup, {sum(live.values())} in use)")
    return {"name": path.name, "size_bytes": path.stat().st_size, "check": check}


def verify_backup(path: Path) -> dict:
    """Prove a backup archive can be read back. Returns the findings; `ok` sums them up."""
    try:
        with zipfile.ZipFile(path) as archive:
            damaged = archive.testzip()  # re-reads every file and compares its checksum
            names = set(archive.namelist())
            if damaged or "manifest.json" not in names or "football.db" not in names:
                return {"ok": False, "problem": f"The archive is damaged or incomplete ({damaged or 'a file is missing'})."}
            manifest = json.loads(archive.read("manifest.json"))
            with tempfile.TemporaryDirectory() as scratch:
                archive.extract("football.db", scratch)
                facts = _inspect_database(Path(scratch) / "football.db")
            frames = sorted(name.removeprefix("media/frames/") for name in names if name.startswith("media/frames/"))
    except (zipfile.BadZipFile, json.JSONDecodeError, sqlite3.DatabaseError, KeyError) as error:
        return {"ok": False, "problem": f"The archive cannot be read: {error}"}

    problems = []
    if facts["integrity_check"] != "ok":
        problems.append(f"the database copy fails SQLite's integrity check ({facts['integrity_check']})")
    if facts["tables"] != manifest.get("tables"):
        problems.append("the database copy does not hold the number of rows recorded when it was made")
    if frames != sorted(manifest.get("frames", [])):
        problems.append("the frame pictures in the archive are not the ones recorded when it was made")
    return {
        "ok": not problems,
        "problem": "; ".join(problems) or None,
        "created_at": manifest.get("created_at"),
        "schema_revision": facts["schema_revision"],
        "rows": sum(facts["tables"].values()),
        "tables": facts["tables"],
        "frame_pictures": len(frames),
    }


def list_backups() -> list[dict]:
    """The backup archives in data/backups, newest first."""
    if not config.BACKUPS_DIR.is_dir():
        return []
    files = sorted((path for path in config.BACKUPS_DIR.glob("football-backup-*.zip") if _BACKUP_NAME.fullmatch(path.name)),
                   key=lambda path: path.name, reverse=True)
    return [{"name": path.name, "size_bytes": path.stat().st_size,
             "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
             .isoformat(timespec="seconds").replace("+00:00", "Z")} for path in files]


def backup_path(name: str) -> Path:
    """The file of a named backup. Only names the app itself produces are accepted."""
    if not _BACKUP_NAME.fullmatch(name):
        raise NotFound("There is no backup with that name.")
    path = config.BACKUPS_DIR / name
    if not path.is_file():
        raise NotFound("There is no backup with that name.")
    return path


def restore_backup(archive_path: Path, data_dir: Path) -> dict:
    """Replace the data in `data_dir` with a backup. ONLY while the server is stopped.

    The current database and pictures are moved to "<data_dir>/replaced-<time>/"
    and kept. Existing backup archives are left where they are.
    """
    archive_path, data_dir = Path(archive_path), Path(data_dir)
    check = verify_backup(archive_path)
    if not check["ok"]:
        raise Invalid(f"This backup failed its check and was not restored: {check['problem']}")

    with zipfile.ZipFile(archive_path) as archive:
        members = [name for name in archive.namelist() if not name.endswith("/")]
        # Only the three kinds of file a backup contains may be written, and only to their own place.
        for name in members:
            if name not in ("football.db", "manifest.json") and not _FRAME_MEMBER.fullmatch(name):
                raise Invalid(f"The archive contains an unexpected file ({name}) and was not restored.")

        data_dir.mkdir(parents=True, exist_ok=True)
        aside = None
        current = [path for path in (data_dir / "football.db", data_dir / "media") if path.exists()]
        if current:
            aside = data_dir / f"replaced-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            aside.mkdir()
            for path in current:
                shutil.move(str(path), str(aside / path.name))

        frames_dir = data_dir / "media" / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        for name in members:
            if name == "manifest.json":
                continue
            target = data_dir / "football.db" if name == "football.db" else frames_dir / Path(name).name
            with archive.open(name) as source, open(target, "wb") as destination:
                shutil.copyfileobj(source, destination)

    return {"restored_from": archive_path.name, "rows": check["rows"], "frame_pictures": check["frame_pictures"],
            "previous_data_moved_to": str(aside) if aside else None}
