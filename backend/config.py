"""Settings and file locations, all in one place.

Everything the app stores for you lives under ONE folder (DATA_DIR):

    backend/data/
        football.db        the SQLite database (players, matches, observations, ...)
        media/frames/      video frames you captured or screenshots you uploaded
        backups/           backup archives made from Settings -> Backup

Set FOOTBALL_DATA_DIR to keep that folder somewhere else (the tests do this so
they can never touch your real data). Optional settings such as an AI key go in
backend/.env, which is ignored by git.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import URL, make_url

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_DIR / "frontend"

# The tests set FOOTBALL_IGNORE_DOTENV so they never pick up your real settings.
if not os.getenv("FOOTBALL_IGNORE_DOTENV"):
    load_dotenv(BACKEND_DIR / ".env")

DATA_DIR = Path(os.getenv("FOOTBALL_DATA_DIR") or BACKEND_DIR / "data").resolve()
DATABASE_FILE = DATA_DIR / "football.db"
MEDIA_DIR = DATA_DIR / "media"
FRAMES_DIR = MEDIA_DIR / "frames"
BACKUPS_DIR = DATA_DIR / "backups"

# SQLite by default. DATABASE_URL exists only as an escape hatch; the app is
# written and tested against SQLite. The address is built from its parts
# (URL.create) rather than by pasting the path into a string, so a data folder
# whose name contains # % ? or spaces cannot be misread.
DATABASE_URL = make_url(os.environ["DATABASE_URL"]) if os.getenv("DATABASE_URL") else URL.create(
    "sqlite", database=str(DATABASE_FILE))

# The server only answers requests addressed to these host names. This is a
# single-user app with no login, so it must not be reachable under other names
# (it blocks a class of attack where a website points its own domain at your machine).
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]

# ── Optional AI assistance ───────────────────────────────────────────────────
# OFF unless you switch it on in backend/.env with  AI_PROVIDER=anthropic .
# Being explicit means an API key that merely happens to be set on this computer
# is never used (and never billed) without you deciding so.
AI_PROVIDER = (os.getenv("AI_PROVIDER") or "").strip().lower()
AI_MODEL = (os.getenv("AI_MODEL") or "claude-opus-5-5").strip()
AI_EFFORT = (os.getenv("AI_EFFORT") or "medium").strip().lower()  # low | medium | high | xhigh | max

# Largest frame image accepted when saving a tactical snapshot (bytes, after decoding).
MAX_FRAME_BYTES = 8 * 1024 * 1024

# Video containers the browser's <video> element can usually play. Whether a
# particular file really plays depends on its codec, which only the browser knows.
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".webm", ".ogv", ".ogg"}


def ensure_data_dirs() -> None:
    """Create the data folders if they do not exist yet. Never deletes anything."""
    for folder in (DATA_DIR, FRAMES_DIR, BACKUPS_DIR):
        folder.mkdir(parents=True, exist_ok=True)
