"""Every page, in a real browser: it loads, keeps its frame, and its main job works.

These catch what the API tests cannot see: a stylesheet rule that breaks the
header, a page that overflows on a phone, a form that does not reach the server.
"""
import re

import pytest
from playwright.sync_api import expect


@pytest.fixture
def populated(live_app):
    """A little of everything, so no page is showing only its empty state."""
    request = live_app.request
    striker = request("POST", "/api/players", {"full_name": "Sam Finisher", "primary_position": "ST", "shirt_number": 9,
                                                "current_team": "Northside FC"})
    stopper = request("POST", "/api/players", {"full_name": "Pat Stopper", "primary_position": "CB"})
    match = request("POST", "/api/matches", {"home_team": "Northside FC", "away_team": "Riverton United",
                                             "match_date": "2026-03-08", "home_score": 2, "away_score": 1})
    request("POST", f"/api/matches/{match['id']}/appearances", {"player_id": striker["id"], "side": "home"})
    request("POST", f"/api/players/{striker['id']}/assessments", {
        "assessed_on": "2026-03-10", "summary": "Sharp movement.", "ratings": [{"attribute": "finishing", "rating": 3}]})
    request("POST", f"/api/players/{striker['id']}/statistics", {
        "scope": "season", "season": "2025/26", "goals": 7, "minutes_played": 940, "source": "Counted from video"})
    request("POST", f"/api/players/{stopper['id']}/statistics", {
        "scope": "season", "season": "2025/26", "minutes_played": 300, "source": "Counted from video"})
    run = {"annotations": [{"uid": "run", "layer": "pitch", "kind": "movement", "points": [[78, 30.5], [92, 24]],
                            "properties": {"recorded_movement": True}}]}
    ids = []
    for time, movement, outcome, diagram in ((612.5, "Diagonal run", "Shot", run), (1934, "Diagonal run", "Goal", None),
                                             (2710, "Channel run", "Not found by the pass", None)):
        body = {"player_ids": [striker["id"]], "match_id": match["id"], "video_time_seconds": time,
                "category": "Off-ball movement", "movement_category": movement, "outcome": outcome,
                "notes": f"Note for the {movement.lower()} at {time}."}
        if diagram:
            body["snapshot"] = diagram
        ids.append(request("POST", "/api/observations", body)["id"])
    request("POST", "/api/notes", {"note_type": "Question for future analysis", "status": "open",
                                   "title": "Same run against a back three?", "observation_ids": [ids[0]]})
    request("POST", "/api/snapshots", {"title": "Standalone idea",
                                       "annotations": [{"uid": "b", "layer": "pitch", "kind": "ball", "points": [[50, 30]]}]})
    return {"striker": striker, "stopper": stopper, "match": match, "observations": ids}


PAGES = [
    "index.html", "players.html", "player.html?id=1", "player.html?id=1#statistics", "player.html?id=1#assessments",
    "player.html?id=1#diagrams", "player.html?id=1#development", "matches.html", "match.html?id=1", "video.html",
    "video.html?match=1", "pitch.html", "pitch.html?snapshot=2", "observations.html", "observations.html?player_id=1",
    "reports.html", "reports.html#compare", "reports.html?player_id=1#player", "reports.html#ai", "notebook.html",
    "notebook.html#ideas", "settings.html",
]


@pytest.mark.parametrize("width", [1440, 390], ids=["desktop", "phone"])
def test_every_page_loads_with_its_frame_intact(page, live_app, populated, width):
    page.set_viewport_size({"width": width, "height": 900})
    for address in PAGES:
        page.goto(f"{live_app.url}/{address}")
        page.wait_for_load_state("networkidle")

        # The navigation strip is a strip: tall enough to hold its links, and they sit inside it.
        header = page.locator("header.bar").bounding_box()
        assert 40 <= header["height"] <= 140, f"{address}: header is {header['height']}px tall"
        link = page.get_by_role("navigation", name="Main").get_by_role("link", name="Dashboard", exact=True)
        box = link.bounding_box()
        assert header["y"] <= box["y"] and box["y"] + box["height"] <= header["y"] + header["height"] + 1, address

        expect(page.locator("h1")).to_be_visible()
        expect(page.get_by_text("Loading…")).to_have_count(0)
        expect(page.locator(".note.error")).to_have_count(0)  # nothing failed to load
        # Nothing forces the whole page to scroll sideways (wide tables scroll inside their own box).
        overflow = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
        assert overflow <= 1, f"{address} at {width}px is {overflow}px wider than the screen"


def test_unknown_values_show_as_not_recorded_never_as_zero(page, live_app, populated):
    page.goto(f"{live_app.url}/player.html?id=1#statistics")
    row = page.get_by_role("row").filter(has_text="2025/26")
    expect(row).to_contain_text("940")
    expect(row).to_contain_text("7")
    # Assists were never recorded: the cell holds the "not recorded" dash, not a 0.
    assert row.locator(".unknown").count() >= 5
    assert "0" not in [cell.strip() for cell in row.locator("td.num").all_inner_texts()]


def test_a_player_is_created_edited_and_assessed_through_the_forms(page, live_app):
    page.expected_problems = ["status of 422"]  # the impossible height below is refused on purpose
    page.goto(f"{live_app.url}/players.html")
    page.get_by_role("button", name="Add player").first.click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Full name").fill("Jo Midfield")
    dialog.get_by_label("Primary position").fill("cm")
    dialog.get_by_label("Current club").fill("Northside FC")
    dialog.get_by_label("Height (cm)").fill("999")  # impossible: the form must say so and save nothing
    dialog.get_by_role("button", name="Add player").click()
    expect(dialog.get_by_text(re.compile("less than or equal to 230"))).to_be_visible()
    assert live_app.request("GET", "/api/players") == []

    dialog.get_by_label("Height (cm)").fill("")  # unknown after all
    dialog.get_by_role("button", name="Add player").click()
    page.wait_for_url(re.compile(r"player\.html\?id=1"))
    expect(page.locator("h1")).to_contain_text("Jo Midfield")
    saved = live_app.request("GET", "/api/players/1")
    assert (saved["primary_position"], saved["height_cm"], saved["current_team"]["name"]) == ("CM", None, "Northside FC")

    # Write an assessment, then a second one: both stay.
    page.get_by_role("tab", name=re.compile("Assessments")).click()
    for summary, rating in (("Tidy but passive.", "2"), ("Now dictates the tempo.", "4")):
        page.get_by_role("button", name="New assessment", exact=True).click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_label("Summary").fill(summary)
        dialog.get_by_label("Passing").select_option(rating)
        dialog.get_by_role("button", name="Save assessment").click()
        expect(page.get_by_text(summary)).to_be_visible()
    assert [a["summary"] for a in live_app.request("GET", "/api/players/1/assessments")] == [
        "Now dictates the tempo.", "Tidy but passive."]  # newest first; the first one was not overwritten
    expect(page.get_by_text("Tidy but passive.")).to_be_visible()  # the earlier opinion is still shown

    # Changing the biography leaves both assessments alone.
    page.get_by_role("button", name="Edit", exact=True).first.click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Current club").fill("Riverton United")
    dialog.get_by_role("button", name="Save changes").click()
    expect(page.locator(".page-head")).to_contain_text("Riverton United")
    assert len(live_app.request("GET", "/api/players/1/assessments")) == 2


def test_a_report_figure_opens_exactly_the_records_behind_it(page, live_app, populated):
    page.goto(f"{live_app.url}/reports.html")
    row = page.get_by_role("row").filter(has_text="Diagonal run").first
    expect(row).to_contain_text("2")
    expect(page.get_by_text("counts of what you chose to record")).to_have_count(1)  # each caveat is said once

    row.get_by_role("link", name="Show these 2").click()
    page.wait_for_url(re.compile(r"observations\.html"))
    expect(page.get_by_text("2 observations match these filters.")).to_be_visible()
    expect(page.locator(".list > li")).to_have_count(2)
    for text in ("Note for the diagonal run at 612.5.", "Note for the diagonal run at 1934."):
        expect(page.get_by_text(text)).to_be_visible()

    # The pitch grid: the one drawn movement ended in the final third, left half-space.
    page.goto(f"{live_app.url}/reports.html")
    cell = page.get_by_role("link", name=re.compile(r"1 in the final third, left half-space"))
    expect(cell).to_be_visible()
    cell.click()
    page.wait_for_url(re.compile(r"observations\.html\?ids="))
    expect(page.locator(".list > li")).to_have_count(1)
    expect(page.get_by_text("behind a figure on the Reports page")).to_be_visible()


def test_players_are_compared_with_the_caveats_in_view(page, live_app, populated):
    page.goto(f"{live_app.url}/reports.html#compare")
    page.get_by_label("Sam Finisher").check()
    page.get_by_label("Pat Stopper").check()
    expect(page.get_by_text("A bigger number does not make a better player")).to_be_visible()
    expect(page.get_by_text("These players do different jobs")).to_be_visible()
    expect(page.get_by_text("Pat Stopper has only 300 recorded minutes")).to_be_visible()
    goals = page.get_by_role("row").filter(has_text=re.compile(r"^Goals"))
    expect(goals).to_contain_text("7")
    expect(goals.locator(".unknown")).to_have_count(1)  # the centre-back's goals: not recorded, not 0


def test_an_observation_becomes_a_linked_coaching_note(page, live_app, populated):
    first = populated["observations"][0]
    page.goto(f"{live_app.url}/observations.html?open={first}")
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("Note for the diagonal run at 612.5.")
    dialog.get_by_role("link", name="Turn into a coaching note").click()

    page.wait_for_url(re.compile(r"notebook\.html"))
    form = page.get_by_role("dialog")
    expect(form.get_by_label("Title")).to_have_value("Off-ball movement: Diagonal run")
    expect(form.get_by_label("Observation numbers it rests on")).to_have_value(str(first))
    form.get_by_label("Note", exact=True).fill("Practise creating separation before the run.")
    form.get_by_role("button", name="Save note").click()
    expect(page.get_by_text("Note saved, linked to the observation")).to_be_visible()

    linked = {n["title"]: n for n in live_app.request("GET", f"/api/notes?observation_id={first}")}
    new_note = linked["Off-ball movement: Diagonal run"]  # the fixture's open question is linked to it too
    assert new_note["body"] == "Practise creating separation before the run."
    assert new_note["player"]["full_name"] == "Sam Finisher" and new_note["match"]["id"] == populated["match"]["id"]
    derived = live_app.request("GET", f"/api/observations/{first}")["derived"]
    assert {"kind": "coaching_note", "title": "Off-ball movement: Diagonal run", "id": new_note["id"]} in derived


def test_backup_export_and_import_from_the_settings_page(page, live_app, populated, tmp_path):
    page.goto(f"{live_app.url}/settings.html")
    page.get_by_role("button", name="Make a backup now").click()
    expect(page.get_by_text(re.compile(r"Backup made and checked: it opens, its database passes"))).to_be_visible()
    assert len(live_app.request("GET", "/api/backups")) == 1

    with page.expect_download() as download:
        page.get_by_role("link", name="Players (CSV)").click()
    exported = tmp_path / "players.csv"
    download.value.save_as(exported)
    assert "Sam Finisher" in exported.read_text(encoding="utf-8-sig")

    # A file with one bad row: checked, reported by line, nothing saved.
    bad = tmp_path / "bad.csv"
    bad.write_text("full_name,height_cm\nGood Player,180\nTall Story,999\n", encoding="utf-8")
    page.locator("#import-file").set_input_files(str(bad))
    page.get_by_role("button", name="Check the file").click()
    report = page.locator(".note.error")
    expect(report).to_contain_text("Nothing was imported")
    expect(report.get_by_role("row").filter(has_text="height_cm")).to_contain_text("3")  # line 3 of the file
    assert len(live_app.request("GET", "/api/players")) == 2

    good = tmp_path / "good.csv"
    good.write_text("full_name,primary_position\nGood Player,cm\n", encoding="utf-8")
    page.locator("#import-file").set_input_files(str(good))
    page.get_by_role("button", name="Import", exact=True).click()
    expect(page.get_by_text("Imported 1 row.")).to_be_visible()
    assert [p["full_name"] for p in live_app.request("GET", "/api/players")] == ["Good Player", "Pat Stopper", "Sam Finisher"]


def test_ai_is_off_by_default_and_the_page_says_how_that_affects_nothing(page, live_app, populated):
    page.goto(f"{live_app.url}/reports.html#ai")
    expect(page.get_by_text("AI assistance is off. Everything else works without it.")).to_be_visible()
    expect(page.get_by_role("button", name="Ask the AI")).to_have_count(0)
