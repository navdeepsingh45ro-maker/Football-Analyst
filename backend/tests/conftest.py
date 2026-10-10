"""Shared test setup. Run the suite from the backend folder:  python -m pytest tests -q"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Must run before anything imports `config` or `database`: point every test at a
# throwaway data folder so tests can never touch your real backend/data.
_data_dir = Path(tempfile.mkdtemp(prefix="football-analyst-tests-"))
os.environ["FOOTBALL_DATA_DIR"] = str(_data_dir)
os.environ.pop("DATABASE_URL", None)
os.environ["ALLOWED_HOSTS"] = "127.0.0.1,localhost,testserver"  # "testserver" is what TestClient calls itself
# Tests must never read your real backend/.env or reach a real AI service.
os.environ["FOOTBALL_IGNORE_DOTENV"] = "1"
for _name in ("AI_PROVIDER", "ANTHROPIC_API_KEY", "AI_MODEL"):
    os.environ.pop(_name, None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import config  # noqa: E402
import database  # noqa: E402

assert str(_data_dir) in str(database.engine.url.database), "Tests must not run against the real database"

from main import app  # noqa: E402
from migrations_runner import run_migrations  # noqa: E402

run_migrations()  # build the schema once, exactly the way the real app does


def pytest_addoption(parser):
    # Used by tests/browser. Declared here because pytest only accepts new
    # command-line options from the top-level conftest.
    parser.addoption("--headed-browser", action="store_true",
                     help="browser tests: show the browser window while they run")


@pytest.fixture(autouse=True)
def clean_data():
    """Every test starts with empty tables and an empty frames folder."""
    yield
    with database.engine.begin() as connection:
        # Children before parents, so the foreign keys are satisfied while deleting.
        for table in reversed(database.Base.metadata.sorted_tables):
            connection.execute(table.delete())
    for leftover in config.FRAMES_DIR.glob("*"):
        leftover.unlink()
    for leftover in config.BACKUPS_DIR.glob("*"):
        if leftover.is_dir():
            shutil.rmtree(leftover)
        else:
            leftover.unlink()


@pytest.fixture
def client() -> TestClient:
    """Talks to the app exactly as the browser would, without starting a server."""
    return TestClient(app)


@pytest.fixture
def db():
    """A database session for tests that need to look underneath the API."""
    session = database.SessionLocal()
    try:
        yield session
    finally:
        session.close()
