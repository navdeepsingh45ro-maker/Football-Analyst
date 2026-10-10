"""Put a backup back. Run it from the backend folder WHILE THE SERVER IS STOPPED:

    python scripts/restore_backup.py data/backups/football-backup-20261010-091500.zip

What it does:
  1. Checks the archive (the same check that runs when a backup is made).
  2. Moves your current database and pictures into data/replaced-<time>/ (kept, not deleted).
  3. Unpacks the backup in their place.
Start the server again afterwards. If the backup is older than the app, the
server upgrades its database on start, as usual.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from errors import AppError  # noqa: E402
from services import backup_service  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    archive = Path(sys.argv[1]).expanduser()
    if not archive.is_file():
        print(f"No such file: {archive}")
        return 2

    check = backup_service.verify_backup(archive)
    if not check["ok"]:
        print(f"This backup failed its check and will not be restored: {check['problem']}")
        return 1
    print(f"Backup made {check['created_at']}: {check['rows']} rows, {check['frame_pictures']} frame pictures.")
    print(f"It will replace the data in: {config.DATA_DIR}")
    print("The current data there will be moved aside, not deleted.")
    print("Make sure the server is stopped (Ctrl+C in its terminal).")
    if input("Type RESTORE to continue: ").strip() != "RESTORE":
        print("Nothing was changed.")
        return 1

    try:
        result = backup_service.restore_backup(archive, config.DATA_DIR)
    except AppError as error:
        print(f"Not restored: {error.detail}")
        return 1
    print(f"Restored {result['rows']} rows and {result['frame_pictures']} frame pictures.")
    if result["previous_data_moved_to"]:
        print(f"Your previous data is in: {result['previous_data_moved_to']}")
    print("Start the server again:  uvicorn main:app")
    return 0


if __name__ == "__main__":
    sys.exit(main())
