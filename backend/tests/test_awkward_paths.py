"""The data folder may sit in a path with spaces or symbols (this project lives under "project 1").

Everything that touches files must still work there: the database itself, the
backup (which opens SQLite through a file: address, where such characters need
care), and a restart.
"""
import pytest

from tests.live_server import LiveServer, free_port


@pytest.mark.parametrize("folder_name", ["project 1", "my data #1 (50% done) & more", "données d'été"])
def test_the_app_works_when_its_data_folder_has_an_awkward_name(tmp_path, folder_name):
    data_dir = tmp_path / folder_name / "data"
    port = free_port()

    with LiveServer(data_dir, port) as server:
        player = server.request("POST", "/api/players", {"full_name": "Path Tester", "current_team": "Northside FC"})
        backup = server.request("POST", "/api/backups")
        about = server.request("GET", "/api/about")
    assert backup["check"]["ok"] is True, backup["check"]
    assert backup["check"]["tables"]["players"] == 1
    assert about["data_folder"] == str(data_dir.resolve())
    assert (data_dir / "football.db").is_file()
    assert (data_dir / "backups" / backup["name"]).is_file()

    with LiveServer(data_dir, port) as server:  # and it comes back after a restart
        assert server.request("GET", f"/api/players/{player['id']}")["full_name"] == "Path Tester"
