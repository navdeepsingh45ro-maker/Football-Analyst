"""Acceptance test J: export records, validate the output, and import them again.
Also: backups are verified when made, and a restored backup really runs."""
import csv
import io
import json
import sqlite3
import urllib.request
import zipfile

import pytest

import config
import database
from services import backup_service
from tests.helpers import add_to_lineup, create_assessment, create_match, create_observation, create_player, sample_diagram
from tests.live_server import LiveServer


def _fill(client) -> dict:
    """One of everything, linked together."""
    striker = create_player(client, full_name="Sam Finisher", primary_position="ST", current_team="Northside FC",
                            date_of_birth="2001-04-12", secondary_positions=["LW"])
    winger = create_player(client, full_name="Lee Wide", primary_position="RW")
    match = create_match(client, competition="Example League", season="2025/26", home_score=2, away_score=1)
    add_to_lineup(client, match["id"], striker["id"], side="home", shirt_number=9)
    video = client.post(f"/api/matches/{match['id']}/videos", json={"location": "https://example.com/match.mp4"}).json()
    create_assessment(client, striker["id"], ratings=[{"attribute": "finishing", "rating": 4, "note": "calm"}])
    client.post(f"/api/players/{striker['id']}/statistics", json={
        "scope": "season", "season": "2025/26", "competition": "Example League", "goals": 7, "minutes_played": 940,
        "extra_metrics": {"touches in box": 55}, "source": "Counted from video"})
    observation = create_observation(
        client, [striker["id"], winger["id"]], match_id=match["id"], video_reference_id=video["id"],
        video_time_seconds=612.5, match_clock_seconds=540, movement_category="Diagonal run", outcome="Shot",
        notes="Starts on the blind side.", confidence="high", snapshot=sample_diagram())
    note = client.post("/api/notes", json={"note_type": "Coaching principle", "title": "Create separation",
                                           "observation_ids": [observation["id"]], "tags": ["movement"]}).json()
    client.post("/api/training-ideas", json={"title": "Check away, then go", "source_note_id": note["id"],
                                             "observation_ids": [observation["id"]], "duration_minutes": 15})
    return {"striker": striker, "winger": winger, "match": match, "observation": observation}


def _fingerprint(get) -> dict:
    """Everything the app would show, fetched through the API (`get` returns parsed JSON)."""
    players = get("/api/players")
    observations = get("/api/observations")["items"]
    return {
        "players": players,
        "assessments": [get(f"/api/players/{p['id']}/assessments") for p in players],
        "statistics": [get(f"/api/players/{p['id']}/statistics") for p in players],
        "matches": [get(f"/api/matches/{m['id']}") for m in get("/api/matches")],
        "observations": [get(f"/api/observations/{o['id']}") for o in observations],
        "notes": get("/api/notes"),
        "ideas": get("/api/training-ideas"),
        "counts": get("/api/dashboard")["counts"],
    }


def _wipe_database() -> None:
    with database.engine.begin() as connection:
        for table in reversed(database.Base.metadata.sorted_tables):
            connection.execute(table.delete())


def _rows(csv_text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(csv_text.lstrip("﻿"))))


# ── JSON: everything out, everything back ────────────────────────────────────
def test_json_export_round_trip_restores_every_record_and_link(client):
    _fill(client)
    before = _fingerprint(lambda path: client.get(path).json())

    response = client.get("/api/export/json")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    export = response.json()
    assert export["format"] == "football-analyst-export" and export["version"] == 1
    assert len(export["tables"]["players"]) == 2
    assert len(export["tables"]["annotations"]) == 16
    assert export["tables"]["observations"][0]["video_time_seconds"] == 612.5
    assert export["tables"]["observations"][0]["created_at"].endswith("Z")  # calendar time, marked as UTC
    assert {"observation_id", "player_id", "role"} <= set(export["tables"]["observation_players"][0])

    # It refuses to pour into a database that already has data: nothing is ever overwritten.
    refused = client.post("/api/import/json", json=export)
    assert refused.status_code == 409
    assert "players" in refused.json()["tables_with_data"]

    _wipe_database()  # stands in for "a fresh, empty copy of the app"; the frame pictures stay on disk
    assert client.get("/api/players").json() == []

    trial = client.post("/api/import/json", json=export, params={"dry_run": True}).json()
    assert trial["saved"] is False and trial["total"] > 30
    assert client.get("/api/players").json() == []  # a dry run changes nothing

    result = client.post("/api/import/json", json=export)
    assert result.status_code == 200, result.text
    assert result.json()["saved"] is True and result.json()["pictures_missing"] == 0

    after = _fingerprint(lambda path: client.get(path).json())
    assert after == before  # same ids, same links, same timestamps, same diagram coordinates


def test_json_import_reports_missing_pictures_instead_of_showing_broken_ones(client):
    _fill(client)
    export = client.get("/api/export/json").json()
    _wipe_database()
    for picture in config.FRAMES_DIR.glob("*"):
        picture.unlink()  # as if the export were loaded on another computer, without the pictures

    result = client.post("/api/import/json", json=export).json()
    assert result["pictures_missing"] == 1
    snapshot = client.get("/api/observations/1").json()["snapshots"][0]
    assert snapshot["frame_image_url"] is None
    assert len(snapshot["annotations"]) == 16  # the drawing itself is complete


@pytest.mark.parametrize("why, damage", [
    ("not an export at all", lambda e: {"hello": "world"}),
    ("another version", lambda e: {**e, "version": 99}),
    ("another database version", lambda e: {**e, "schema_revision": "something-else"}),
    ("an unknown table", lambda e: {**e, "tables": {**e["tables"], "wizards": []}}),
    ("an unknown column", lambda e: {**e, "tables": {**e["tables"], "players": [{**e["tables"]["players"][0], "mana": 9}]}}),
    ("a link to a player who is not in the file", lambda e: {**e, "tables": {**e["tables"], "players": []}}),
    ("an unreadable date", lambda e: {**e, "tables": {**e["tables"], "matches": [
        {**e["tables"]["matches"][0], "match_date": "the eighth of March"}]}}),
])
def test_a_damaged_json_export_imports_nothing(client, why, damage):
    _fill(client)
    export = client.get("/api/export/json").json()
    _wipe_database()
    response = client.post("/api/import/json", json=damage(export))
    assert response.status_code == 422, f"{why}: {response.text}"
    # All or nothing: not one row was kept.
    assert client.get("/api/players").json() == [] and client.get("/api/matches").json() == [], why
    assert client.get("/api/observations").json()["total"] == 0, why


# ── CSV ──────────────────────────────────────────────────────────────────────
def test_csv_exports_are_readable_and_complete(client):
    made = _fill(client)

    players = _rows(client.get("/api/export/csv/players").text)
    assert [(p["id"], p["full_name"], p["current_team"], p["secondary_positions"], p["height_cm"]) for p in players] == [
        ("1", "Sam Finisher", "Northside FC", "LW", ""), ("2", "Lee Wide", "", "", "")]  # unknown is empty, not 0

    matches = _rows(client.get("/api/export/csv/matches").text)
    assert (matches[0]["home_team"], matches[0]["away_team"], matches[0]["home_score"], matches[0]["season"]) == (
        "Northside FC", "Riverton United", "2", "2025/26")

    statistics = _rows(client.get("/api/export/csv/statistics").text)
    assert (statistics[0]["player_name"], statistics[0]["goals"], statistics[0]["assists"]) == ("Sam Finisher", "7", "")
    assert json.loads(statistics[0]["extra_metrics"]) == {"touches in box": 55}

    observations = _rows(client.get("/api/export/csv/observations").text)
    row = observations[0]
    assert row["id"] == str(made["observation"]["id"])
    assert (row["player_ids"], row["player_names"], row["primary_player_id"]) == ("1; 2", "Sam Finisher; Lee Wide", "1")
    assert (row["video_time"], row["match_clock"]) == ("10:12.5", "9:00")  # clocks, readable and exact
    assert (row["match"], row["match_date"], row["diagram_count"]) == ("Northside FC v Riverton United", "2026-03-08", "1")
    assert row["created_at"].endswith("Z")

    # The observation export honours the same filters as the observation list.
    assert len(_rows(client.get("/api/export/csv/observations", params={"outcome": "Goal"}).text)) == 0
    assert len(_rows(client.get("/api/export/csv/observations", params={"player_id": 2}).text)) == 1
    assert client.get("/api/export/csv/dragons").status_code == 422


def _import(client, entity, text, **params):
    return client.post(f"/api/import/csv/{entity}", content=text.encode("utf-8"),
                       headers={"Content-Type": "text/csv"}, params=params)


def test_csv_import_adds_valid_rows(client):
    text = ("full_name,date_of_birth,primary_position,current_team,height_cm,secondary_positions\n"
            "Robin Keeper,1998-07-01,gk,Riverton United,191,\n"
            "Jo Midfield,,CM,Northside FC,,DM; AM\n"
            "\n")  # a trailing empty line is not a row
    trial = _import(client, "players", text, dry_run=True).json()
    assert (trial["rows"], trial["would_create"], trial["saved"], trial["errors"]) == (2, 2, False, [])
    assert client.get("/api/players").json() == []

    result = _import(client, "players", text).json()
    assert (result["created"], result["saved"], result["errors"]) == (2, True, [])
    by_name = {p["full_name"]: p for p in client.get("/api/players").json()}
    assert by_name["Robin Keeper"]["primary_position"] == "GK"  # the same tidying as the form
    assert by_name["Robin Keeper"]["height_cm"] == 191
    assert by_name["Jo Midfield"]["height_cm"] is None and by_name["Jo Midfield"]["date_of_birth"] is None
    assert by_name["Jo Midfield"]["secondary_positions"] == ["DM", "AM"]


def test_one_bad_row_cancels_the_whole_csv_import_and_is_reported(client):
    create_player(client, full_name="Already Here", date_of_birth="1999-01-01")
    text = ("full_name,date_of_birth,height_cm,preferred_foot\n"
            "Good Player,2000-01-01,180,left\n"          # line 2: fine
            "Tall Story,2000-01-01,999,left\n"           # line 3: impossible height
            ",2000-01-01,180,both\n"                     # line 4: no name
            "Already Here,1999-01-01,,\n"                # line 5: already recorded
            "Odd Foot,31/12/2000,,middle\n")             # line 6: two problems
    result = _import(client, "players", text).json()
    assert result["saved"] is False and result["created"] == 0
    problems = {(error["row"], error["column"]) for error in result["errors"]}
    assert problems == {(3, "height_cm"), (4, "full_name"), (5, None), (6, "date_of_birth"), (6, "preferred_foot")}
    assert any("already recorded" in error["message"] for error in result["errors"] if error["row"] == 5)
    # Not even the good row was saved.
    assert [p["full_name"] for p in client.get("/api/players").json()] == ["Already Here"]


@pytest.mark.parametrize("why, text, fragment", [
    ("empty file", "", "empty or has no header"),
    ("a misspelt column", "full_name,hieght_cm\nSomeone,180\n", "Unknown column(s): hieght_cm"),
    ("too many cells", "full_name\nSomeone,extra,cells\n", None),
])
def test_malformed_csv_files_are_refused_clearly(client, why, text, fragment):
    response = _import(client, "players", text)
    body = response.json()
    if fragment:
        assert response.status_code == 422 and fragment in body["detail"], why
    else:
        assert body["saved"] is False and body["errors"][0]["row"] == 2 and "more cells" in body["errors"][0]["message"]
    assert client.get("/api/players").json() == []
    assert _import(client, "wizards", "a\n1\n").status_code == 422
    not_text = client.post("/api/import/csv/players", content=b"\xff\xfe\x00bad", headers={"Content-Type": "text/csv"})
    assert not_text.status_code == 422 and "UTF-8" in not_text.json()["detail"]


def test_an_exported_csv_can_be_imported_into_a_fresh_copy(client):
    _fill(client)
    files = {entity: client.get(f"/api/export/csv/{entity}").text for entity in ("players", "matches")}
    observations_file = client.get("/api/export/csv/observations").text
    _wipe_database()

    for entity, text in files.items():
        result = _import(client, entity, text).json()
        assert result["saved"] is True, result
        assert "id" in result["ignored_columns"]  # export-only columns are named, not silently dropped
    assert [p["full_name"] for p in client.get("/api/players").json()] == ["Lee Wide", "Sam Finisher"]
    assert client.get("/api/matches").json()[0]["title"] == "Northside FC v Riverton United"

    # Observations refer to players and a match by id. In a fresh copy the video link does not exist,
    # so that row is refused with the reason, and nothing is half-imported.
    refused = _import(client, "observations", observations_file).json()
    assert refused["saved"] is False and refused["errors"][0]["row"] == 2

    # Without the video link it imports, keeping players, clock times and text.
    rows = _rows(observations_file)
    rows[0]["video_reference_id"] = ""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    accepted = _import(client, "observations", buffer.getvalue()).json()
    assert accepted["saved"] is True, accepted
    observation = client.get("/api/observations").json()["items"][0]
    assert (observation["video_time_seconds"], observation["match_clock_seconds"]) == (612.5, 540)
    assert (observation["movement_category"], observation["notes"]) == ("Diagonal run", "Starts on the blind side.")
    assert [(p["full_name"], p["role"]) for p in observation["players"]] == [("Sam Finisher", "primary"),
                                                                           ("Lee Wide", "involved")]


def test_statistics_and_observations_can_be_imported_by_player_name(client):
    create_player(client, full_name="Sam Finisher")
    create_match(client)
    stats = ("player_name,scope,season,goals,shots,source\n"
             "Sam Finisher,season,2025/26,7,,Counted from video\n")
    assert _import(client, "statistics", stats).json()["saved"] is True
    line = client.get("/api/players/1/statistics").json()[0]
    assert (line["goals"], line["shots"]) == (7, None)  # the empty cell is "not recorded", not 0

    observations = ("player_names,match_id,video_time,category,notes\n"
                    "Sam Finisher,1,32:14,positioning,=SUM(1+1) looks like a formula but is my note\n"
                    "Nobody Known,1,1:00,positioning,\n")
    result = _import(client, "observations", observations).json()
    assert result["saved"] is False
    assert result["errors"] == [{"row": 3, "column": None,
                                 "message": "No player is called 'Nobody Known'. Import or add the player first."}]

    assert _import(client, "observations", observations.rsplit("Nobody", 1)[0]).json()["saved"] is True
    observation = client.get("/api/observations").json()["items"][0]
    assert observation["video_time_seconds"] == 1934.0 and observation["category"] == "Positioning"
    # Text that looks like a spreadsheet formula is exported so that it is shown, not run, and survives the trip.
    exported = _rows(client.get("/api/export/csv/observations").text)[0]["notes"]
    assert exported.startswith("'=SUM")
    assert observation["notes"].startswith("=SUM")


# ── Backups ──────────────────────────────────────────────────────────────────
def test_a_backup_is_checked_when_it_is_made(client):
    _fill(client)
    response = client.post("/api/backups")
    assert response.status_code == 201, response.text
    backup = response.json()
    check = backup["check"]
    assert check["ok"] is True and check["problem"] is None
    assert check["tables"]["players"] == 2 and check["tables"]["annotations"] == 16
    assert check["frame_pictures"] == 1
    assert [entry["name"] for entry in client.get("/api/backups").json()] == [backup["name"]]

    downloaded = client.get(f"/api/backups/{backup['name']}")
    assert downloaded.status_code == 200 and downloaded.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        names = archive.namelist()
        assert "football.db" in names and "manifest.json" in names
        assert sum(name.startswith("media/frames/") for name in names) == 1
        assert json.loads(archive.read("manifest.json"))["tables"]["observations"] == 1

    assert client.get("/api/backups/../../etc/passwd").status_code == 404
    assert client.get("/api/backups/football-backup-00000000-000000.zip").status_code == 404


def test_a_backup_that_does_not_hold_the_live_data_fails_its_check(client, monkeypatch):
    """A copy can be perfectly healthy and still be a copy of the wrong thing (this really
    happened: a data folder with # in its name was mis-addressed and an empty database was
    copied). So the check compares the backup with the database in use, not just with itself."""
    _fill(client)

    def copies_an_empty_database(source, destination):
        connection = sqlite3.connect(destination)
        connection.execute("CREATE TABLE placeholder (x)")
        connection.execute("DROP TABLE placeholder")
        connection.commit()
        connection.close()
        return destination

    monkeypatch.setattr(backup_service, "copy_sqlite_database", copies_an_empty_database)
    check = client.post("/api/backups").json()["check"]
    assert check["ok"] is False
    assert "does not hold the same number of rows as the database in use" in check["problem"]


def test_a_damaged_backup_fails_its_check(client, tmp_path):
    _fill(client)
    name = client.post("/api/backups").json()["name"]
    good = config.BACKUPS_DIR / name

    truncated = tmp_path / "truncated.zip"
    truncated.write_bytes(good.read_bytes()[:2000])
    assert backup_service.verify_backup(truncated)["ok"] is False

    # An archive whose database no longer matches what was recorded when it was made.
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(good) as source, zipfile.ZipFile(tampered, "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "football.db":
                scratch = tmp_path / "scratch.db"
                scratch.write_bytes(data)
                connection = sqlite3.connect(scratch)
                connection.execute("PRAGMA foreign_keys=OFF")
                connection.execute("DELETE FROM players")
                connection.commit()
                connection.close()
                data = scratch.read_bytes()
            target.writestr(item, data)
    check = backup_service.verify_backup(tampered)
    assert check["ok"] is False and "number of rows" in check["problem"]
    with pytest.raises(Exception, match="failed its check"):
        backup_service.restore_backup(tampered, tmp_path / "restore-target")
    assert not (tmp_path / "restore-target" / "football.db").exists()  # nothing was written


def test_a_restored_backup_really_runs(client, tmp_path):
    """The proof that backups work: restore one into an empty folder and start the real app on it."""
    _fill(client)
    before = _fingerprint(lambda path: client.get(path).json())
    archive = config.BACKUPS_DIR / client.post("/api/backups").json()["name"]

    restored_dir = tmp_path / "restored"
    result = backup_service.restore_backup(archive, restored_dir)
    assert result["previous_data_moved_to"] is None  # the folder was empty
    assert result["frame_pictures"] == 1

    with LiveServer(restored_dir) as server:
        after = _fingerprint(lambda path: server.request("GET", path))
        picture_url = after["observations"][0]["snapshots"][0]["frame_image_url"]
        with urllib.request.urlopen(server.url + picture_url, timeout=10) as response:
            assert response.read()[:8] == b"\x89PNG\r\n\x1a\n"
    assert after == before

    # Restoring over existing data moves that data aside instead of deleting it.
    again = backup_service.restore_backup(archive, restored_dir)
    aside = again["previous_data_moved_to"]
    assert aside and (restored_dir / aside.split("/")[-1] / "football.db").is_file()
    assert (restored_dir / "football.db").is_file()
