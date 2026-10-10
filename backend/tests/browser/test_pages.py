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
    "reports.html", "reports.html#compare", "reports.html?player_id=1#player", "coach.html", "notebook.html",
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
    page.goto(f"{live_app.url}/coach.html")
    expect(page.get_by_text("AI assistance is off. Everything else works without it.")).to_be_visible()
    expect(page.get_by_role("button", name="Ask the coach")).to_have_count(0)


def test_the_dashboard_shows_the_next_step_until_the_first_analysis_exists(page, live_app):
    page.goto(f"{live_app.url}/index.html")
    steps = page.get_by_role("listitem")
    expect(page.get_by_role("heading", name="Start here")).to_be_visible()
    expect(steps.filter(has_text="Add a player").get_by_role("link", name="Go to Players")).to_be_visible()

    live_app.request("POST", "/api/players", {"full_name": "Sam Finisher"})
    page.reload()
    done = steps.filter(has_text="Add a player")
    expect(done).to_contain_text("Done")
    expect(done.get_by_role("link")).to_have_count(0)  # a finished step no longer asks to be done
    expect(steps.filter(has_text="Add a match").get_by_role("link", name="Go to Matches")).to_be_visible()


def test_extra_observation_filters_are_one_press_away_and_open_when_in_use(page, live_app, populated):
    page.goto(f"{live_app.url}/observations.html")
    expect(page.get_by_label("Player", exact=True)).to_be_visible()
    expect(page.get_by_label("Outcome")).to_be_hidden()
    page.get_by_role("button", name="More filters").click()
    page.get_by_label("Outcome").fill("Goal")
    expect(page.get_by_text("1 observation matches these filters.")).to_be_visible()
    page.get_by_role("button", name="Fewer filters").click()
    expect(page.get_by_role("button", name="More filters (1 in use)")).to_be_visible()  # hidden, but not forgotten

    page.goto(f"{live_app.url}/observations.html?outcome=Shot")  # arriving with one in use: it is in view
    expect(page.get_by_label("Outcome")).to_be_visible()
    expect(page.get_by_label("Outcome")).to_have_value("Shot")


def test_a_conversation_with_the_coach(page, live_app, populated):
    """The page's behaviour, with the AI's replies supplied by the test: no AI service is involved."""
    striker, first = populated["striker"], populated["observations"][0]
    asked = []

    def reply(route):
        body = route.request.post_data_json
        asked.append(body)
        route.fulfill(json={
            "question": body["question"], "scope": {"player": {"id": striker["id"], "full_name": "Sam Finisher"}, "match": None},
            "label": "AI-generated. Check before you rely on it.", "provider": "google", "model": "test-model", "note": None,
            "refused": False, "generated_at": "2026-10-10T10:00:00Z",
            "evidence_used": {"players": 1, "observations": 3, "assessments": 1, "statistics": 1, "observations_left_out": 0},
            "answer": f"Reply number {len(asked)}.",
            "points": [
                {"statement": "He repeats the diagonal run.", "kind": "recorded", "unsupported": False,
                 "references": [{"id": f"obs-{first}", "kind": "observation", "record_id": first, "player_id": None}]},
                {"statement": "He scored forty goals.", "kind": "recorded", "unsupported": True, "references": []},
                {"statement": "A rondo trains scanning.", "kind": "general", "unsupported": False, "references": []}],
            "follow_ups": ["And in training?"], "insufficient_evidence": False, "evidence_note": "",
            "invalid_references_removed": 0, "unsupported_statements": 1})

    page.route("**/api/ai/status", lambda route: route.fulfill(json={
        "enabled": True, "provider": "google", "model": "test-model", "message": "AI assistance is on.", "tasks": {}}))
    page.route("**/api/ai/coach", reply)

    page.goto(f"{live_app.url}/player.html?id={striker['id']}")
    page.get_by_role("link", name="Ask the coach").click()  # arrives with that player already chosen
    expect(page.get_by_label("Ask about a player")).to_have_value(str(striker["id"]))
    expect(page.get_by_role("button", name="What should Sam Finisher work on in training?")).to_be_visible()

    page.get_by_label("Your question").fill("What does he do well?")
    page.get_by_label("Your question").press("Enter")
    expect(page.get_by_text("Reply number 1.")).to_be_visible()
    expect(page.get_by_text("About Sam Finisher")).to_be_visible()
    expect(page.get_by_text("It was shown 1 player profile, 3 observations, 1 assessment and 1 stat line.")).to_be_visible()
    assert asked[0]["player_id"] == striker["id"] and asked[0]["match_id"] is None and asked[0]["history"] == []

    # The three kinds of statement are told apart in words.
    points = page.locator(".points > li")
    expect(points.nth(0)).to_contain_text("From your records")
    expect(points.nth(1)).to_contain_text("Cites no record of yours. Do not rely on it.")
    expect(points.nth(2)).to_contain_text("General coaching advice")
    points.nth(0).get_by_role("link", name=f"observation #{first}").click()  # a reference opens the record itself
    expect(page.get_by_role("dialog")).to_contain_text("Note for the diagonal run at 612.5.")
    page.keyboard.press("Escape")

    # A follow-up carries the conversation so far.
    page.get_by_role("button", name="And in training?").first.click()
    expect(page.get_by_text("Reply number 2.")).to_be_visible()
    assert asked[1]["question"] == "And in training?"
    assert asked[1]["history"] == [{"question": "What does he do well?", "answer": "Reply number 1."}]

    # Nothing is saved until asked; then it lands in the notebook, linked to the player and the observation.
    assert not [note for note in live_app.request("GET", "/api/notes") if note["note_type"] == "AI-generated draft"]
    page.get_by_role("button", name="Keep in the notebook").first.click()
    expect(page.get_by_role("link", name="Open it in the notebook")).to_be_visible()
    kept = [note for note in live_app.request("GET", "/api/notes") if note["note_type"] == "AI-generated draft"]
    assert len(kept) == 1 and kept[0]["player"]["id"] == striker["id"] and "AI-generated" in kept[0]["tags"]
    assert "(General coaching advice) A rondo trains scanning." in kept[0]["body"]


def test_a_player_is_filled_in_from_the_web_for_you_to_check(page, live_app):
    """The form's behaviour, with Wikidata's answers supplied by the test: nothing leaves this computer."""
    live_app.request("POST", "/api/players", {"full_name": "Pat Stopper", "nationality": "Otherland",
                                              "current_team": "Riverton United"})
    found = {"query": "finisher", "source": "Wikidata", "results": [
        {"id": "Q900001", "name": "Sam Finisher", "description": "Examplelandic footballer (born 2001)",
         "url": "https://www.wikidata.org/wiki/Q900001"}]}
    details = {
        "id": "Q900001", "name": "Sam Finisher", "description": "Examplelandic footballer (born 2001)",
        "fields": {"full_name": "Sam Finisher", "date_of_birth": "2001-04-12", "height_cm": 183, "preferred_foot": "left",
                   "current_team": "Northside F.C.", "shirt_number": 9, "nationality": "Exampleland"},
        "notes": ['Position: Wikidata says "winger", which does not name one exact position (it could be RW or LW). '
                  "Choose it yourself."],
        "source": {"name": "Wikidata", "url": "https://www.wikidata.org/wiki/Q900001",
                   "wikipedia_url": "https://en.wikipedia.org/wiki/Sam_Finisher"},
        "checked_on": "2026-10-10"}
    page.route(re.compile(r"/api/lookup/players\?"), lambda route: route.fulfill(json=found))
    page.route(re.compile(r"/api/lookup/players/Q900001$"), lambda route: route.fulfill(json=details))
    saved_players = lambda: live_app.request("GET", "/api/players")  # noqa: E731

    # ── A new player ─────────────────────────────────────────────────────────
    page.goto(f"{live_app.url}/players.html")
    page.get_by_role("button", name="Add player").first.click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Primary position").fill("rw")  # typed by hand: must survive
    search = dialog.get_by_label("Fill in from the web (optional)")
    search.fill("finisher")
    search.press("Enter")  # Enter searches; it must not save the half-empty form
    expect(dialog.get_by_text("Examplelandic footballer (born 2001)")).to_be_visible()
    assert len(saved_players()) == 1

    dialog.get_by_role("button", name="Use the details of Sam Finisher").click()
    expect(dialog.get_by_text("Filled in from Wikidata: name, date of birth, height, preferred foot, club, "
                              "shirt number, nationality.")).to_be_visible()
    expect(dialog.get_by_text("it could be RW or LW")).to_be_visible()  # what was left empty, and why
    expect(dialog.get_by_label("Full name")).to_have_value("Sam Finisher")
    expect(dialog.get_by_label("Date of birth")).to_have_value("2001-04-12")
    expect(dialog.get_by_label("Height (cm)")).to_have_value("183")
    expect(dialog.get_by_label("Preferred foot")).to_have_value("left")
    expect(dialog.get_by_label("Primary position")).to_have_value("rw")
    expect(dialog.get_by_label("Notes")).to_have_value(
        "Details filled in from Wikidata (https://www.wikidata.org/wiki/Q900001) on 10 Oct 2026.")
    expect(dialog.get_by_role("link", name="Wikipedia")).to_have_attribute("href", "https://en.wikipedia.org/wiki/Sam_Finisher")
    assert len(saved_players()) == 1  # filling the form saves nothing

    dialog.get_by_role("button", name="Add player").click()  # you checked it; now it is saved like anything typed
    page.wait_for_url(re.compile(r"player\.html\?id=2"))
    saved = live_app.request("GET", "/api/players/2")
    assert (saved["full_name"], saved["date_of_birth"], saved["height_cm"], saved["preferred_foot"], saved["primary_position"],
            saved["current_team"]["name"], saved["shirt_number"], saved["nationality"]) == (
        "Sam Finisher", "2001-04-12", 183, "left", "RW", "Northside F.C.", 9, "Exampleland")
    assert "Wikidata" in saved["notes"]

    # ── An existing player: only the empty boxes are filled ──────────────────
    page.goto(f"{live_app.url}/player.html?id=1")
    page.get_by_role("button", name="Edit", exact=True).first.click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_label("Fill in from the web (optional)")).to_have_value("Pat Stopper")
    dialog.get_by_role("button", name="Search the web").click()
    dialog.get_by_role("button", name="Use the details of Sam Finisher").click()
    expect(dialog.get_by_text('Kept what you had typed for: name (Wikidata says "Sam Finisher"); club (Wikidata says '
                              '"Northside F.C."); nationality (Wikidata says "Exampleland").')).to_be_visible()
    expect(dialog.get_by_label("Full name")).to_have_value("Pat Stopper")
    expect(dialog.get_by_label("Current club")).to_have_value("Riverton United")
    expect(dialog.get_by_label("Nationality")).to_have_value("Otherland")
    expect(dialog.get_by_label("Height (cm)")).to_have_value("183")  # this one was empty
    dialog.get_by_role("button", name="Cancel").click()
    assert live_app.request("GET", "/api/players/1")["height_cm"] is None  # cancelled: nothing changed
