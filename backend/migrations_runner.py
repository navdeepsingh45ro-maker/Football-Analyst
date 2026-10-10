"""Database migrations: brings the database schema up to date when the server starts.

HOW TO CHANGE THE DATABASE SCHEMA
---------------------------------
Never edit tables by hand. Instead:

  1. Edit the model in models/ (add a column, change a length, ...). A brand
     new model file must also be imported in models/__init__.py.
  2. From the backend folder, against a THROWAWAY copy of the data so a draft
     can never touch your real database:
         FOOTBALL_DATA_DIR=/tmp/fa-scratch python -c "from migrations_runner import run_migrations; run_migrations()"
         FOOTBALL_DATA_DIR=/tmp/fa-scratch alembic revision --autogenerate -m "short description"
  3. Open the new file in alembic/versions/ and READ it. Autogenerate is a
     draft: it cannot tell a rename from a drop + add, and a new NOT NULL column
     on a table that already has rows needs a default.
  4. Start the server. The migration is applied automatically.

tests/test_migrations.py fails if a model changed but no migration was added.

WHAT run_migrations() DOES AT STARTUP
-------------------------------------
  a) New, empty database        -> creates every table (alembic upgrade head).
  b) Already up to date         -> nothing.
  c) Behind (a new migration)   -> FIRST copies football.db into data/backups/
                                   as pre-migration-<time>.db, THEN upgrades.
                                   If an upgrade ever goes wrong, that copy is
                                   your data exactly as it was.
"""
import logging
from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

import config
import database
import models  # noqa: F401  (registers every model on Base.metadata)
from services.backup_service import copy_sqlite_database

# Own handler so the one-line summary shows up in the server output even though
# the app does not configure logging itself.
logger = logging.getLogger("migrations")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    logger.addHandler(_handler)
    logger.propagate = False

BACKEND_DIR = Path(__file__).resolve().parent


def _alembic_config(engine: Engine) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["engine"] = engine  # alembic/env.py uses this instead of database.engine
    cfg.attributes["from_runner"] = True  # keep the app's logging setup untouched
    return cfg


def current_revision(engine: Engine | None = None) -> str | None:
    """The migration the database is at right now (None for a database with no tables yet)."""
    with (engine or database.engine).connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def head_revision(engine: Engine | None = None) -> str | None:
    """The newest migration that exists in alembic/versions/."""
    return ScriptDirectory.from_config(_alembic_config(engine or database.engine)).get_current_head()


def run_migrations(engine: Engine | None = None, backup_dir: Path | None = None) -> str:
    """Bring the schema up to date and return a one-line summary of what happened.

    `engine` defaults to the app's engine (tests pass their own).
    """
    engine = engine or database.engine
    cfg = _alembic_config(engine)
    head = head_revision(engine)
    current = current_revision(engine)
    existing_tables = set(inspect(engine).get_table_names())
    app_tables = set(database.Base.metadata.tables)

    if current == head:
        summary = f"database is up to date ({head})"
    elif current is None and not (existing_tables & app_tables):
        command.upgrade(cfg, "head")
        summary = f"new database, created all tables ({head})"
    elif current is None:
        # Tables exist but Alembic has no record of them. That never happens through
        # the app itself, so stop rather than guess what state the data is in.
        raise RuntimeError(
            "The database has tables but no migration history (alembic_version is missing). "
            "Refusing to change it automatically. Restore a backup, or ask for help before deleting anything."
        )
    else:
        backup_note = ""
        if engine.dialect.name == "sqlite" and engine.url.database:
            folder = backup_dir or config.BACKUPS_DIR
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = copy_sqlite_database(Path(engine.url.database), folder / f"pre-migration-{stamp}.db")
            backup_note = f", safety copy saved as {backup.name}"
        command.upgrade(cfg, "head")
        summary = f"upgraded database from {current} to {head}{backup_note}"

    logger.info("Migrations: %s", summary)
    return summary
