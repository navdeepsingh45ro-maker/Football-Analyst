"""The migrations and the models must describe the same database, and upgrades must be safe."""
import sqlite3

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

import database
import migrations_runner
from migrations_runner import current_revision, head_revision, run_migrations


def _fresh_engine(tmp_path):
    return create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")


def test_models_and_migrations_agree():
    """Fails when a model was changed but no migration was written for it."""
    with database.engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, database.Base.metadata)
    assert differences == [], (
        "The models and the migrated database differ. Write a migration "
        f"(see migrations_runner.py). Differences: {differences}"
    )


def test_running_migrations_again_changes_nothing():
    assert run_migrations().startswith("database is up to date")


def test_new_database_gets_every_table(tmp_path):
    engine = _fresh_engine(tmp_path)
    summary = run_migrations(engine)
    assert summary.startswith("new database")
    assert set(database.Base.metadata.tables) <= set(inspect(engine).get_table_names())
    assert current_revision(engine) == head_revision(engine)


def test_database_is_copied_before_an_upgrade(tmp_path, monkeypatch):
    engine = _fresh_engine(tmp_path)
    run_migrations(engine)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO teams (name, team_type, created_at, updated_at) "
            "VALUES ('Safety FC', 'club', '2026-01-01', '2026-01-01')"
        ))
        # Pretend the database was made by an older version of the app.
        connection.execute(text("UPDATE alembic_version SET version_num = 'an-older-revision'"))
    # There is only one real migration so far, so stand in for the upgrade itself.
    # What is being tested is that the copy is taken first and is complete.
    monkeypatch.setattr(migrations_runner.command, "upgrade", lambda cfg, target: None)

    summary = run_migrations(engine, backup_dir=tmp_path / "backups")

    backups = list((tmp_path / "backups").glob("pre-migration-*.db"))
    assert len(backups) == 1
    assert backups[0].name in summary
    copy = sqlite3.connect(backups[0])
    try:
        assert copy.execute("SELECT name FROM teams").fetchall() == [("Safety FC",)]
        assert copy.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    finally:
        copy.close()


def test_tables_without_migration_history_are_left_alone(tmp_path):
    engine = _fresh_engine(tmp_path)
    run_migrations(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
    with pytest.raises(RuntimeError, match="no migration history"):
        run_migrations(engine)
    # Nothing was dropped or recreated by the refusal.
    assert "teams" in inspect(engine).get_table_names()
