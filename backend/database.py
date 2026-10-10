"""Database connection: one SQLite file opened through SQLAlchemy.

Three things every other module imports from here:

    Base         parent class of every model in models/
    SessionLocal factory for database sessions
    get_db       FastAPI dependency that hands a route one session per request
"""
from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

import config

DATABASE_URL = config.DATABASE_URL  # a sqlalchemy URL object (see config.py)
IS_SQLITE = DATABASE_URL.get_backend_name() == "sqlite"

if IS_SQLITE:
    config.ensure_data_dirs()  # SQLite cannot create the file inside a folder that is missing
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    """SQLite ignores FOREIGN KEY rules unless each new connection switches them on.

    Without this, deleting a team would silently leave matches pointing at a
    team that no longer exists. With it, the database itself refuses.
    """
    if not IS_SQLITE:
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Predictable names for indexes and constraints. Alembic needs every constraint
# to have a name before it can change or drop it later, especially on SQLite.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def get_db():
    """One session per request. Anything not committed is rolled back on close."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
