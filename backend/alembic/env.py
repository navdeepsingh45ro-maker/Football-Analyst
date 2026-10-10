"""Alembic environment: wires Alembic to the app's own database and models."""
from logging.config import fileConfig

from alembic import context

import database
import models  # noqa: F401  (registers every model on Base.metadata)
from database import Base

config = context.config

# Only configure logging when run from the `alembic` command line. When the app
# starts migrations itself (migrations_runner.py) we must not reset its logging.
if config.config_file_name is not None and not config.attributes.get("from_runner"):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _options(dialect_name: str) -> dict:
    return {
        "target_metadata": target_metadata,
        "compare_type": True,
        # SQLite cannot ALTER most things in place; batch mode rebuilds the table.
        "render_as_batch": dialect_name == "sqlite",
    }


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of connecting (`alembic upgrade head --sql`)."""
    url = database.DATABASE_URL
    context.configure(
        url=url.render_as_string(hide_password=False),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_options(url.get_backend_name()),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # The runner (and tests) may hand in a specific engine; otherwise use the app's.
    engine = config.attributes.get("engine") or database.engine
    with engine.connect() as connection:
        context.configure(connection=connection, **_options(connection.dialect.name))
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
