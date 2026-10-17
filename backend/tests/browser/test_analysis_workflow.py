"""The core workflow, in a real browser.

Acceptance test L:  open match -> pause video -> open analysis -> annotate -> save
                    -> retrieve from the player's profile -> inspect the saved diagram.
                    The video stays in view beside the drawing the whole time.
Acceptance test F:  resize the display; annotations stay on their spot.
Acceptance test K:  an unplayable video and a match with no video still leave a way to work.

How positions are checked: a shape drawn at, say, 40% across and 50% down the
picture must (a) be STORED as (0.40, 0.50), and (b) be DRAWN with its centre at
40% / 50% of the picture's box, at every window size.
"""
import os
import re
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import expect

ASSETS = Path(__file__).parent / "assets"
CLIP = ASSETS / "test-clip.mp4"  # a 6 second, 640 x 360 test pattern made with ffmpeg
SCREENSHOT = ASSETS / "screenshot.png"  # 960 x 540

# Tool buttons, by their accessible names (see TOOLS in frontend/js/editor/panels.js).
STUDIED = "Marker for the player you are studying"
DEFENDER = "Defending player marker (an opponent when your player attacks)"
BALL = "Ball marker"
RUN = "Movement arrow: a run without the ball"
SPACE = "Highlighted space or zone"
ANGLE = "Angle measurement between three points"

# How exactly a click must land where it was aimed, as a fraction of the surface. Chromium can click
# between pixels; Safari's engine (FOOTBALL_BROWSER=webkit) clicks on whole pixels, about 0.003 of the
# drawing's height each, and may settle a paused video on the nearest frame.
SAFARI_ENGINE = os.environ.get("FOOTBALL_BROWSER", "chromium") == "webkit"
NEAR = 0.008 if SAFARI_ENGINE else 0.004
SAME_MOMENT = 0.05 if SAFARI_ENGINE else 1e-6
FRAME = '.surface-box[data-layer="frame"] svg'
PITCH = '.surface-box[data-layer="pitch"] svg'


def pitch(x_metres: float, y_metres: float) -> tuple[float, float]:
    """A pitch position as a fraction of the pitch surface (105 x 68 m plus a 4 m strip all round)."""
    return (x_metres + 4) / 113, (y_metres + 4) / 76


def screen_point(page, selector: str, fraction: tuple[float, float]) -> tuple[float, float]:
    box = page.locator(selector).bounding_box()
    return box["x"] + box["width"] * fraction[0], box["y"] + box["height"] * fraction[1]


def tool(page, name: str) -> None:
    page.get_by_role("button", name=name, exact=True).click()


def click_on(page, selector: str, fraction: tuple[float, float]) -> None:
    page.locator(selector).scroll_into_view_if_needed()
    page.mouse.click(*screen_point(page, selector, fraction))


def drag_on(page, selector: str, start: tuple[float, float], end: tuple[float, float]) -> None:
    page.locator(selector).scroll_into_view_if_needed()
    x0, y0 = screen_point(page, selector, start)
    x1, y1 = screen_point(page, selector, end)
    page.mouse.move(x0, y0)
    page.mouse.down()
    page.mouse.move((x0 + x1) / 2, (y0 + y1) / 2)
    page.mouse.move(x1, y1)
    page.mouse.up()


def clear_of_the_video(page, selector: str) -> None:
    """In a narrow window the video stays at the top; scroll so that `selector` is wholly below it."""
    page.locator(selector).evaluate("(element) => element.scrollIntoView({ block: 'end' })")


def drawn_at(page, surface: str, shape: str) -> tuple[float, float]:
    """Where a shape's centre is DRAWN, as a fraction of its surface's box on screen."""
    outer = page.locator(surface).bounding_box()
    inner = page.locator(f"{surface} {shape}").bounding_box()
    return ((inner["x"] + inner["width"] / 2 - outer["x"]) / outer["width"],
            (inner["y"] + inner["height"] / 2 - outer["y"]) / outer["height"])


def wait_until(page, condition: str, timeout: float = 10.0) -> None:
    """Poll a JavaScript function until it returns something truthy.

    Playwright's own wait_for_function works by evaluating text as code inside the
    page. This app's Content-Security-Policy forbids exactly that (on purpose), and
    the tests keep the policy switched on, so they poll from the outside instead.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if page.evaluate(condition):
            return
        page.wait_for_timeout(50)
    raise AssertionError(f"Timed out waiting for: {condition}")


def video_state(page) -> dict:
    return page.evaluate("() => { const v = document.querySelector('video');"
                         " return { time: v.currentTime, paused: v.paused, width: v.videoWidth, height: v.videoHeight }; }")


def seconds(clock: str) -> float:
    total = 0.0
    for part in clock.split(":"):
        total = total * 60 + float(part)
    return total


@pytest.fixture
def scene(live_app):
    """A match with a playable local video, and two players in its lineup."""
    striker = live_app.request("POST", "/api/players", {"full_name": "Sam Finisher", "primary_position": "ST"})
    stopper = live_app.request("POST", "/api/players", {"full_name": "Pat Stopper", "primary_position": "CB"})
    match = live_app.request("POST", "/api/matches", {"home_team": "Northside FC", "away_team": "Riverton United",
                                                      "match_date": "2026-03-08"})
    live_app.request("POST", f"/api/matches/{match['id']}/appearances",
                     {"player_id": striker["id"], "side": "home", "shirt_number": 9})
    live_app.request("POST", f"/api/matches/{match['id']}/appearances",
                     {"player_id": stopper["id"], "side": "away", "shirt_number": 4})
    video = live_app.request("POST", f"/api/matches/{match['id']}/videos", {"location": str(CLIP)})
    assert video["playback"]["mode"] == "html5" and video["playback"]["available"] is True
    return {"striker": striker, "stopper": stopper, "match": match, "video": video}


def test_watch_pause_analyse_annotate_save_and_find_it_again(page, live_app, scene):
    match_id, striker_id = scene["match"]["id"], scene["striker"]["id"]

    # ── Open the match and watch ─────────────────────────────────────────────
    page.goto(f"{live_app.url}/video.html?match={match_id}")
    # Ready once its size and length are known. (Safari loads no picture until the video is played.)
    wait_until(page, "() => { const v = document.querySelector('video'); return Boolean(v) && v.readyState >= 1; }")
    analyse = page.get_by_role("button", name="Analyse this moment")
    expect(analyse).to_be_visible()  # in the bar under the video
    # Muted, because Safari only lets a page start a video by itself when it makes no sound.
    page.evaluate("() => { const v = document.querySelector('video'); v.muted = true; return v.play(); }")
    wait_until(page, "() => document.querySelector('video').currentTime > 1.2")
    page.snap("1-watching")

    # ── Pause by pressing Analyse ────────────────────────────────────────────
    analyse.click()
    expect(page.locator(FRAME)).to_be_visible()
    paused = video_state(page)
    assert paused["paused"] is True
    assert (paused["width"], paused["height"]) == (640, 360)
    assert paused["time"] > 1.2

    # The timestamp was captured from the video, to the fraction of a second.
    time_field = page.get_by_role("textbox", name="Video time")
    assert seconds(time_field.input_value()) == pytest.approx(paused["time"], abs=0.001)
    # The paused frame was captured and is what the drawing surface shows.
    assert page.locator(f"{FRAME} image").get_attribute("href").startswith("data:image/jpeg;base64,")

    # ── The video stays in view beside the drawing: watch and analyse at the same time ──
    video_box = page.locator("video").bounding_box()
    frame_box = page.locator(FRAME).bounding_box()
    assert video_box["x"] + video_box["width"] <= frame_box["x"], "side by side, the video on the left"
    for box in (video_box, frame_box):
        assert box["y"] >= 0 and box["y"] + box["height"] <= 900, "both wholly in view at once"

    # ── Say who it is about ──────────────────────────────────────────────────
    page.get_by_role("button", name="Add Sam Finisher").click()  # offered because he is in the lineup

    # ── Draw over the frame ──────────────────────────────────────────────────
    tool(page, STUDIED)
    click_on(page, FRAME, (0.40, 0.50))
    tool(page, DEFENDER)
    click_on(page, FRAME, (0.55, 0.45))
    click_on(page, FRAME, (0.60, 0.62))  # the tool stays on: a second defender with one more click
    tool(page, BALL)
    click_on(page, FRAME, (0.30, 0.70))
    tool(page, RUN)
    drag_on(page, FRAME, (0.40, 0.50), (0.62, 0.38))
    tool(page, SPACE)
    drag_on(page, FRAME, (0.62, 0.22), (0.86, 0.44))

    # ── Rebuild the situation on the pitch ───────────────────────────────────
    tool(page, STUDIED)
    click_on(page, PITCH, pitch(78, 30.5))
    tool(page, DEFENDER)
    click_on(page, PITCH, pitch(84, 27))
    click_on(page, PITCH, pitch(84.5, 38))
    tool(page, BALL)
    click_on(page, PITCH, pitch(67, 13))
    tool(page, RUN)
    drag_on(page, PITCH, pitch(78, 30.5), pitch(92, 24))
    tool(page, ANGLE)
    for corner in (pitch(67, 13), pitch(78, 30.5), pitch(105, 34)):  # ball, player, centre of the goal
        click_on(page, PITCH, corner)
    page.snap("2-annotated")

    # Live measurements appear, labelled as estimates.
    measurements = page.locator(".measures")
    expect(measurements).to_contain_text("Studied player 9 to the ball")
    expect(measurements).to_contain_text("the recorded movement")
    expect(page.get_by_text("Estimates. They are only as accurate")).to_be_visible()

    # ── Acceptance test F, while editing: resize, and the marker stays put ───
    assert drawn_at(page, FRAME, 'g[data-kind="subject"]') == pytest.approx((0.40, 0.50), abs=NEAR)
    page.set_viewport_size({"width": 900, "height": 1000})  # narrow: the layout stacks, the surfaces change size
    assert drawn_at(page, FRAME, 'g[data-kind="subject"]') == pytest.approx((0.40, 0.50), abs=NEAR)
    assert drawn_at(page, PITCH, 'g[data-kind="subject"]') == pytest.approx(pitch(78, 30.5), abs=NEAR)
    # The video stays at the top of a narrow window, smaller, still in view.
    assert page.locator("video").bounding_box()["height"] <= 0.31 * 1000
    # A click at the new size is still stored at the right place (checked after saving, below).
    tool(page, "Attacking player marker (a teammate when your player attacks)")
    clear_of_the_video(page, FRAME)
    click_on(page, FRAME, (0.20, 0.30))
    page.set_viewport_size({"width": 1440, "height": 900})

    # ── Write it down and save ───────────────────────────────────────────────
    page.get_by_label("Movement", exact=True).fill("diagonal run")
    page.get_by_label("Outcome").fill("Shot")
    page.get_by_label("Your interpretation").fill("Starts on the blind side of the centre-back, then cuts across him.")
    page.get_by_role("button", name="Save observation").click()
    expect(page.get_by_text(re.compile(r"Observation #\d+ saved"))).to_be_visible()

    # ── Ready for the next moment; the video still paused, at exactly the same moment ──
    expect(page.locator(FRAME)).to_have_count(0)  # a fresh moment has no picture yet
    expect(page.locator(".draft-head h2")).to_have_text("New moment")
    expect(page.get_by_text("Sam Finisher (studied)")).to_be_visible()  # the player carries over to the next moment
    after = video_state(page)
    assert after["paused"] is True, "saving must not resume playback"
    assert after["time"] == pytest.approx(paused["time"], abs=SAME_MOMENT)
    expect(page.locator(".desk-moments")).to_contain_text("Off-ball movement: Diagonal run")
    page.snap("3-saved")

    # ── What was stored ──────────────────────────────────────────────────────
    listed = live_app.request("GET", f"/api/observations?player_id={striker_id}")
    assert listed["total"] == 1
    observation = live_app.request("GET", f"/api/observations/{listed['items'][0]['id']}")
    assert observation["video_time_seconds"] == pytest.approx(paused["time"], abs=0.001)
    assert observation["match"]["id"] == match_id
    assert observation["video_reference_id"] == scene["video"]["id"]
    assert [(p["full_name"], p["role"]) for p in observation["players"]] == [("Sam Finisher", "primary")]
    assert (observation["movement_category"], observation["outcome"]) == ("Diagonal run", "Shot")

    snapshot = observation["snapshots"][0]
    assert (snapshot["frame_width"], snapshot["frame_height"]) == (640, 360)  # the video's real frame size
    assert snapshot["frame_source"] == "video_capture"
    with urllib.request.urlopen(live_app.url + snapshot["frame_image_url"]) as response:
        assert response.read()[:3] == b"\xff\xd8\xff"  # a JPEG picture of the frame

    def stored(layer, kind):
        return [a for a in snapshot["annotations"] if a["layer"] == layer and a["kind"] == kind]

    # Frame positions are fractions of the picture, not pixels.
    assert stored("frame", "subject")[0]["points"][0] == pytest.approx([0.40, 0.50], abs=NEAR)
    assert stored("frame", "ball")[0]["points"][0] == pytest.approx([0.30, 0.70], abs=NEAR)
    assert [a["points"][0] for a in stored("frame", "defender")] == [pytest.approx([0.55, 0.45], abs=NEAR),
                                                                     pytest.approx([0.60, 0.62], abs=NEAR)]
    assert stored("frame", "movement")[0]["points"] == [pytest.approx([0.40, 0.50], abs=NEAR),
                                                        pytest.approx([0.62, 0.38], abs=NEAR)]
    assert stored("frame", "zone")[0]["points"] == [pytest.approx([0.62, 0.22], abs=NEAR),
                                                    pytest.approx([0.86, 0.44], abs=NEAR)]
    # The marker placed while the window was a different size landed where it was clicked.
    assert stored("frame", "attacker")[0]["points"][0] == pytest.approx([0.20, 0.30], abs=NEAR)
    # Pitch positions are metres.
    assert stored("pitch", "subject")[0]["points"][0] == pytest.approx([78, 30.5], abs=0.15)
    assert stored("pitch", "ball")[0]["points"][0] == pytest.approx([67, 13], abs=0.15)
    run = stored("pitch", "movement")[0]
    assert run["points"] == [pytest.approx([78, 30.5], abs=0.15), pytest.approx([92, 24], abs=0.15)]
    assert run["properties"] == {"recorded_movement": True}
    assert len(stored("pitch", "angle")[0]["points"]) == 3
    # The studied-player markers were linked to the chosen player and took his shirt number.
    assert {(a["player_id"], a["label"]) for a in snapshot["annotations"] if a["kind"] == "subject"} == {(striker_id, "9")}

    # ── Letting the video run on does not move the saved timestamp ───────────
    page.evaluate("() => { document.querySelector('video').currentTime = 4.5; }")
    wait_until(page, "() => !document.querySelector('video').seeking")
    again = live_app.request("GET", f"/api/observations/{observation['id']}")
    assert again["video_time_seconds"] == observation["video_time_seconds"]
    assert again["updated_at"] == observation["updated_at"]

    # ── Find it again from the player's profile ──────────────────────────────
    page.goto(f"{live_app.url}/player.html?id={striker_id}#diagrams")
    card = page.locator(".diagram-card")
    expect(card).to_have_count(1)
    saved_frame = ".diagram-card .diagram > div:nth-child(1) svg"
    saved_pitch = ".diagram-card .diagram > div:nth-child(2) svg"
    expect(page.locator(f"{saved_frame} image")).to_have_attribute("href", snapshot["frame_image_url"])
    wait_until(page, "() => [...document.querySelectorAll('.diagram-card image')].every(i => i.getBBox().width > 0)")
    expect(page.locator(f'{saved_frame} g[data-kind="defender"]')).to_have_count(2)
    expect(page.locator(f'{saved_pitch} g[data-kind="angle"]')).to_have_count(1)
    page.snap("4-profile")

    # Acceptance test F again, on the SAVED diagram: same spot of the picture at every size.
    for width in (1440, 1024, 700, 420):
        page.set_viewport_size({"width": width, "height": 900})
        assert drawn_at(page, saved_frame, 'g[data-kind="subject"]') == pytest.approx((0.40, 0.50), abs=0.006), width
        assert drawn_at(page, saved_frame, 'g[data-kind="ball"]') == pytest.approx((0.30, 0.70), abs=0.006), width
        assert drawn_at(page, saved_pitch, 'g[data-kind="subject"]') == pytest.approx(pitch(78, 30.5), abs=0.006), width
        assert drawn_at(page, saved_pitch, 'g[data-kind="ball"]') == pytest.approx(pitch(67, 13), abs=0.006), width
        # The picture itself is never stretched: its box keeps the frame's 16:9 shape.
        box = page.locator(saved_frame).bounding_box()
        assert box["width"] / box["height"] == pytest.approx(640 / 360, rel=0.01), width
    page.set_viewport_size({"width": 1440, "height": 900})

    # ── And read the written observation there too ───────────────────────────
    page.get_by_role("button", name="Open observation").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("Starts on the blind side of the centre-back")
    expect(dialog).to_contain_text("Diagonal run")


def test_the_pitch_can_be_drawn_on_without_a_mouse(page, live_app):
    """Keyboard only: choose a tool, place it, nudge it, delete it, undo."""
    page.goto(f"{live_app.url}/pitch.html")
    surface = page.locator(PITCH)
    expect(surface).to_be_visible()

    page.get_by_role("button", name=BALL, exact=True).focus()
    page.keyboard.press("Enter")  # choose the Ball tool
    surface.focus()
    page.keyboard.press("Enter")  # place it in the middle of the pitch
    expect(page.locator(f'{PITCH} g[data-kind="ball"]')).to_have_count(1)
    assert drawn_at(page, PITCH, 'g[data-kind="ball"]') == pytest.approx(pitch(52.5, 34), abs=NEAR)

    page.keyboard.press("Tab")  # move focus onto the ball
    page.keyboard.press("Enter")  # select it
    x_box = page.get_by_label("Position distance from own goal line, metres")
    y_box = page.get_by_label("Position distance from left touchline, metres")
    assert (x_box.input_value(), y_box.input_value()) == ("52.5", "34")

    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowDown")  # half a metre per press
    assert (x_box.input_value(), y_box.input_value()) == ("53.5", "34.5")
    page.keyboard.press("Shift+ArrowLeft")  # five times as far
    assert x_box.input_value() == "51"

    # Typing exact coordinates is the other alternative to dragging.
    x_box.fill("94")
    y_box.fill("34")
    y_box.press("Tab")
    assert drawn_at(page, PITCH, 'g[data-kind="ball"]') == pytest.approx(pitch(94, 34), abs=NEAR)

    page.locator(f'{PITCH} g[data-kind="ball"]').focus()
    page.keyboard.press("Delete")
    expect(page.locator(f'{PITCH} g[data-kind="ball"]')).to_have_count(0)
    page.get_by_role("button", name="Undo the last change (Ctrl/Cmd + Z)").click()
    expect(page.locator(f'{PITCH} g[data-kind="ball"]')).to_have_count(1)
    assert drawn_at(page, PITCH, 'g[data-kind="ball"]') == pytest.approx(pitch(94, 34), abs=NEAR)


def test_a_standalone_pitch_diagram_is_saved_and_reopened(page, live_app):
    page.goto(f"{live_app.url}/pitch.html")
    tool(page, STUDIED)
    click_on(page, PITCH, pitch(94, 34))  # on the penalty spot
    tool(page, BALL)
    click_on(page, PITCH, pitch(83, 34))  # 11 m behind
    expect(page.locator(".measures")).to_contain_text("11.0 m")
    # 2 * atan(3.66 / 11) = 36.8 degrees. A browser that only clicks on whole pixels lands the marker a
    # touch off the spot, so a shade less is accepted here; the exact figure is checked in the geometry tests.
    expect(page.locator(".measures")).to_contain_text(re.compile(r"spans 36\.[6-9]°"))

    page.get_by_label("Title").fill("Penalty spot reference")
    page.get_by_role("button", name="Save diagram").click()
    expect(page.get_by_text("Diagram saved")).to_be_visible()

    saved = live_app.request("GET", "/api/snapshots")
    assert [(d["title"], d["shape_count"]) for d in saved] == [("Penalty spot reference", 2)]

    page.goto(f"{live_app.url}/pitch.html?snapshot={saved[0]['id']}")
    expect(page.get_by_label("Title")).to_have_value("Penalty spot reference")
    assert drawn_at(page, PITCH, 'g[data-kind="subject"]') == pytest.approx(pitch(94, 34), abs=NEAR)
    assert drawn_at(page, PITCH, 'g[data-kind="ball"]') == pytest.approx(pitch(83, 34), abs=NEAR)

    # Change the reopened diagram and save it again: same diagram, updated, no copy.
    tool(page, DEFENDER)
    click_on(page, PITCH, pitch(97, 38))
    page.get_by_role("button", name="Save diagram").click()
    expect(page.get_by_text("Diagram saved")).to_be_visible()
    again = live_app.request("GET", "/api/snapshots")
    assert [(d["id"], d["shape_count"]) for d in again] == [(saved[0]["id"], 3)]


def test_a_moment_can_be_analysed_without_a_playable_video(page, live_app):
    """The documented manual fallback: type the timestamp, add a screenshot, draw, save."""
    player = live_app.request("POST", "/api/players", {"full_name": "Sam Finisher"})
    match = live_app.request("POST", "/api/matches", {"home_team": "Northside FC", "away_team": "Riverton United"})

    page.goto(f"{live_app.url}/video.html?match={match['id']}")
    expect(page.get_by_text("No video is linked to this match")).to_be_visible()
    expect(page.get_by_role("button", name="Analyse this moment")).to_have_count(0)  # nothing pretends to be playable
    expect(page.get_by_role("button", name="Watch it in another window")).to_be_visible()  # any window can still be used

    # The moment is ready to be filled in by hand, beside it.
    expect(page.get_by_text("No picture of this moment yet")).to_be_visible()
    page.get_by_role("textbox", name="Video time").fill("32:14")
    page.get_by_label("Choose a screenshot").set_input_files(str(SCREENSHOT))
    expect(page.locator(FRAME)).to_be_visible()
    tool(page, BALL)
    click_on(page, FRAME, (0.5, 0.5))

    page.get_by_label("Add another player by name").fill("Sam Finisher")
    page.get_by_label("Add another player by name").press("Enter")
    page.get_by_role("button", name="Save observation").click()
    expect(page.get_by_text(re.compile(r"Observation #\d+ saved"))).to_be_visible()

    observation = live_app.request("GET", "/api/observations/1")
    assert observation["video_time_seconds"] == 1934.0  # 32:14, typed by hand
    assert observation["video_reference_id"] is None
    assert [p["id"] for p in observation["players"]] == [player["id"]]
    snapshot = observation["snapshots"][0]
    assert (snapshot["frame_width"], snapshot["frame_height"], snapshot["frame_source"]) == (960, 540, "upload")
    assert snapshot["annotations"][0]["points"][0] == pytest.approx([0.5, 0.5], abs=NEAR)


def test_a_video_the_browser_cannot_play_is_explained_not_hidden(page, live_app, tmp_path):
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"this is not really a video file")
    match = live_app.request("POST", "/api/matches", {"home_team": "Northside FC", "away_team": "Riverton United"})
    live_app.request("POST", f"/api/matches/{match['id']}/videos", {"location": str(broken)})
    page.expected_problems = ["Failed to load resource"]  # the browser logs the failed video itself

    page.goto(f"{live_app.url}/video.html?match={match['id']}")
    problem = page.get_by_role("alert")
    expect(problem).to_be_visible()
    expect(problem).to_contain_text("typing the timestamp and adding a screenshot")
    expect(page.get_by_role("button", name="Analyse this moment")).to_be_hidden()
    # What still works: the moment beside it, by hand, and watching it in another app's window.
    expect(page.get_by_text("No picture of this moment yet")).to_be_visible()
    expect(page.get_by_role("button", name="Watch it in another window instead")).to_be_visible()


def test_reopening_a_saved_drawing_to_change_it(page, live_app, scene):
    striker_id = scene["striker"]["id"]
    created = live_app.request("POST", "/api/observations", {
        "player_ids": [striker_id], "match_id": scene["match"]["id"], "video_time_seconds": 2.48,
        "category": "Positioning", "notes": "First version.",
        "snapshot": {"annotations": [{"uid": "ball-1", "layer": "pitch", "kind": "ball", "points": [[60, 30]]}]}})

    page.goto(f"{live_app.url}/video.html?observation={created['id']}")
    expect(page.locator(f'{PITCH} g[data-kind="ball"]')).to_have_count(1)
    assert page.get_by_role("textbox", name="Video time").input_value() == "0:02.48"  # shown exactly as stored

    tool(page, DEFENDER)
    click_on(page, PITCH, pitch(70, 40))
    page.get_by_label("Your interpretation").fill("Second version.")
    page.get_by_role("button", name="Save changes").click()
    page.wait_for_url(re.compile(r"observations\.html"))

    after = live_app.request("GET", f"/api/observations/{created['id']}")
    assert after["id"] == created["id"]  # edited in place, no copy
    assert live_app.request("GET", "/api/observations")["total"] == 1
    assert after["notes"] == "Second version."
    assert after["video_time_seconds"] == 2.48  # untouched, so unchanged
    shapes = {a["uid"]: a for a in after["snapshots"][0]["annotations"]}
    assert shapes["ball-1"]["points"] == [[60, 30]]  # the existing shape kept its identity and position
    assert len(shapes) == 2


# A stand-in for YouTube's embedded player. It speaks the same messages as the real one
# (checked by hand against the real player), so the page can be tested without the network.
YOUTUBE_STAND_IN = """<!doctype html><meta charset="utf-8"><title>stand-in player</title>
<body style="margin:0;background:#234"><script>
let time = 75.5, state = 1;
const tell = (event, info) => parent.postMessage(JSON.stringify({ event, info, id: 1, channel: 'widget' }), '*');
addEventListener('message', (message) => {
  const asked = JSON.parse(message.data);
  if (asked.event === 'listening') tell('initialDelivery', { currentTime: time, playerState: state, duration: 5400 });
  if (asked.event !== 'command') return;
  if (asked.func === 'pauseVideo') { state = 2; time = 75.75; tell('infoDelivery', { playerState: 2, currentTime: time }); }
  if (asked.func === 'playVideo') { state = 1; tell('infoDelivery', { playerState: 1 }); }
  if (asked.func === 'seekTo') { time = asked.args[0]; tell('infoDelivery', { currentTime: time }); }
  parent.postMessage(JSON.stringify({ event: 'stand-in-was-asked', func: asked.func, args: asked.args }), '*');
});
</script></body>"""


def test_a_youtube_match_is_paused_timed_and_analysed_with_one_button(page, live_app):
    player = live_app.request("POST", "/api/players", {"full_name": "Sam Finisher"})
    match = live_app.request("POST", "/api/matches", {"home_team": "Northside FC", "away_team": "Riverton United"})
    video = live_app.request("POST", f"/api/matches/{match['id']}/videos", {"location": "https://www.youtube.com/watch?v=abcdefghijk"})
    opened = []
    page.route("https://www.youtube-nocookie.com/**", lambda route: (
        opened.append(route.request.url), route.fulfill(content_type="text/html", body=YOUTUBE_STAND_IN)))
    # Note everything the page asks of the player.
    page.add_init_script("""window.asked = []; addEventListener('message', (message) => {
        try {
            const said = JSON.parse(message.data);
            // Leave out the request to be told about errors, sent once the player answers.
            if (said.event === 'stand-in-was-asked' && said.func !== 'addEventListener') window.asked.push([said.func, said.args]);
        } catch {}
    });""")
    asked = lambda: page.evaluate("() => window.asked")  # noqa: E731

    page.goto(f"{live_app.url}/video.html?match={match['id']}&t=42")
    analyse = page.get_by_role("button", name="Analyse this moment")
    expect(analyse).to_be_visible()
    expect(page.get_by_text("at 1:15")).to_be_visible()  # the player's own time, shown without asking you
    assert "enablejsapi=1" in opened[0] and "start=42" in opened[0] and f"origin=http%3A%2F%2F127.0.0.1%3A{live_app.port}" in opened[0]
    expect(page.get_by_role("button", name="Watch it in another window instead")).to_be_visible()  # if it will not play here

    # ── One press: the video is paused and its time is read ──────────────────
    analyse.click()
    step = page.locator(".dropzone")
    expect(page.locator(".draft-head")).to_contain_text("1:15")
    expect(page.get_by_role("textbox", name="Video time")).to_have_value("1:15.75")
    expect(step).to_contain_text("Now add the picture of this moment")
    expect(step).to_contain_text("turn on one-click pictures")  # the way to get it without YouTube's buttons on it
    assert asked() == [["pauseVideo", []]]
    expect(page.locator(".viewer iframe")).to_be_visible()  # the paused video is still there, beside the moment

    # ── The picture goes in, and the workspace opens with the time already filled ──
    step.get_by_label("Choose a screenshot").set_input_files(str(SCREENSHOT))
    expect(page.locator(FRAME)).to_be_visible()
    expect(page.get_by_role("textbox", name="Video time")).to_have_value("1:15.75")
    tool(page, BALL)
    click_on(page, FRAME, (0.5, 0.5))
    page.get_by_label("Add another player by name").fill("Sam Finisher")
    page.get_by_label("Add another player by name").press("Enter")

    # ── One press saves and carries on watching ──────────────────────────────
    page.get_by_role("button", name="Save and keep watching").click()
    expect(page.get_by_text(re.compile(r"Observation #\d+ saved"))).to_be_visible()
    expect(analyse).to_be_visible()
    wait_until(page, "() => window.asked.length === 2")
    assert asked()[1] == ["playVideo", []]

    observation = live_app.request("GET", "/api/observations/1")
    assert observation["video_time_seconds"] == 75.75 and observation["video_reference_id"] == video["id"]
    assert [p["id"] for p in observation["players"]] == [player["id"]]
    assert (observation["snapshots"][0]["frame_width"], observation["snapshots"][0]["frame_source"]) == (960, "upload")

    # ── A saved moment takes the player back to it ───────────────────────────
    page.locator(".desk-moments").get_by_role("button", name=re.compile("1:15")).click()
    wait_until(page, "() => window.asked.length === 3")
    assert asked()[2] == ["seekTo", [75.75, True]]

    # ── Keys: back five seconds, forward five seconds, pause ────────────────
    page.locator("h1").click()  # the keyboard belongs to the page, not to a box or the player
    page.keyboard.press("j")
    expect(page.locator(".watch-clock")).to_have_text("at 1:10")  # the player says where it is now
    page.keyboard.press("l")
    expect(page.locator(".watch-clock")).to_have_text("at 1:15")
    page.keyboard.press("k")
    wait_until(page, "() => window.asked.length === 6")
    assert asked()[3:] == [["seekTo", [70.75, True]], ["seekTo", [75.75, True]], ["pauseVideo", []]]

    # ── Without a picture: the pitch is there at once ────────────────────────
    analyse.click()
    expect(page.locator(PITCH)).to_be_visible()
    expect(page.get_by_text("Now add the picture of this moment")).to_be_visible()


# What the browser would hand over after you agree to share the screen: a picture of the whole page,
# twice as large as the page (a high-resolution screen). The headless test browser cannot really share
# its screen, so this draws that picture itself from where things actually are on the page: the video
# area green with a red centre, and the two marks wherever the page is showing them. With
# window.pausedLook set, the video area is covered in white, as a paused player covers it with its buttons.
SHARED_SCREEN_STAND_IN = """
MediaDevices.prototype.getDisplayMedia = async () => {
  const scale = 2;
  const canvas = document.createElement('canvas');
  canvas.width = innerWidth * scale;
  canvas.height = innerHeight * scale;
  const pen = canvas.getContext('2d');
  const fill = (colour, left, top, width, height) => { pen.fillStyle = colour; pen.fillRect(left * scale, top * scale, width * scale, height * scale); };
  const paint = () => {
    fill('rgb(22,38,63)', 0, 0, innerWidth, innerHeight);
    const video = document.querySelector('.viewer');
    if (video) {
      const box = video.getBoundingClientRect();
      fill('rgb(30,120,60)', box.left, box.top, box.width, box.height);
      fill('rgb(200,40,40)', box.left + box.width / 4, box.top + box.height / 4, box.width / 2, box.height / 2);
      if (window.pausedLook) fill('rgb(255,255,255)', box.left, box.top, box.width, box.height);
    }
    for (const mark of document.querySelectorAll('.capture-mark')) {
      if (getComputedStyle(mark).display === 'none') continue;
      const box = mark.getBoundingClientRect();
      const [first, second] = mark.classList.contains('top-left') ? ['#ff00ff', '#00ffff'] : ['#00ffff', '#ff00ff'];
      fill(first, box.left, box.top, box.width / 2, box.height);
      fill(second, box.left + box.width / 2, box.top, box.width / 2, box.height);
    }
  };
  paint();
  setInterval(paint, 40);
  return canvas.captureStream(25);
};
"""


def test_with_one_click_pictures_on_analyse_takes_the_picture_of_the_video_itself(page, live_app):
    live_app.request("POST", "/api/players", {"full_name": "Sam Finisher"})
    match = live_app.request("POST", "/api/matches", {"home_team": "Northside FC", "away_team": "Riverton United"})
    live_app.request("POST", f"/api/matches/{match['id']}/videos", {"location": "https://youtu.be/abcdefghijk"})
    page.route("https://www.youtube-nocookie.com/**", lambda route: route.fulfill(content_type="text/html", body=YOUTUBE_STAND_IN))
    page.add_init_script(SHARED_SCREEN_STAND_IN)

    page.goto(f"{live_app.url}/video.html?match={match['id']}")
    expect(page.locator(".capture-mark").first).to_be_hidden()  # no marks until sharing is on
    page.get_by_role("button", name="Turn on one-click pictures").click()
    expect(page.get_by_role("status").filter(has_text="One-click pictures are on")).to_be_visible()
    expect(page.get_by_role("button", name="One-click pictures are on")).to_have_attribute("aria-pressed", "true")
    video_box = page.locator(".viewer").bounding_box()

    # One press: picture, pause, time. No screenshot, no typing.
    page.get_by_role("button", name="Analyse this moment").click()
    expect(page.locator(FRAME)).to_be_visible()
    expect(page.get_by_role("textbox", name="Video time")).to_have_value("1:15.75")
    expect(page.get_by_text("Now add the picture of this moment.")).to_have_count(0)

    page.get_by_label("Add another player by name").fill("Sam Finisher")
    page.get_by_label("Add another player by name").press("Enter")
    page.get_by_role("button", name="Save observation").click()
    expect(page.get_by_text(re.compile(r"Observation #\d+ saved"))).to_be_visible()

    snapshot = live_app.request("GET", "/api/observations/1")["snapshots"][0]
    assert snapshot["frame_source"] == "video_capture"
    # The stored picture is the video area and nothing else: same shape, at the shared picture's resolution (or the size limit).
    assert snapshot["frame_width"] / snapshot["frame_height"] == pytest.approx(video_box["width"] / video_box["height"], rel=0.01)
    assert snapshot["frame_width"] == pytest.approx(min(1600, video_box["width"] * 2), abs=3)
    colours = colours_of(page, snapshot["frame_image_url"])
    green, red = pytest.approx([30, 120, 60], abs=14), pytest.approx([200, 40, 40], abs=14)  # JPEG shifts colours slightly
    assert all(colour == green for colour in colours["edges"]), colours  # cropped right to the video's edges, no page around it
    assert colours["middle"] == red
    assert all(colour == green for colour in colours["outsideRed"]) and all(colour == red for colour in colours["insideRed"]), colours

    # ── Paused with YouTube's own button: the picture is from before its buttons covered the video ──
    # The test presses play and pause "inside" the player, as you would, by sending the player those messages itself.
    page.evaluate("""() => {
        document.querySelector('.viewer iframe').contentWindow.postMessage(JSON.stringify({ event: 'command', func: 'playVideo', args: [] }), '*');
    }""")
    page.wait_for_timeout(1200)  # it plays for a moment: the app keeps its frames
    page.evaluate("""() => {
        window.pausedLook = true;  // from now on the shared picture shows the paused player's buttons over the video
        document.querySelector('.viewer iframe').contentWindow.postMessage(JSON.stringify({ event: 'command', func: 'pauseVideo', args: [] }), '*');
    }""")
    page.wait_for_timeout(700)
    page.get_by_role("button", name="Analyse this moment").click()
    expect(page.locator(".frame-choice")).not_to_have_count(0)  # the frames of the last seconds, to choose from
    expect(page.get_by_text("Sam Finisher (studied)")).to_be_visible()  # carried over from the moment before
    page.get_by_role("button", name="Save observation").click()
    expect(page.get_by_text(re.compile(r"Observation #2 saved"))).to_be_visible()
    second = live_app.request("GET", "/api/observations/2")["snapshots"][0]
    assert colours_of(page, second["frame_image_url"])["middle"] == red, "not the white of the paused player's buttons"

    # ── Moved while paused, to look again: the frames kept from before the pause show another moment ──
    page.evaluate("""() => {
        document.querySelector('.viewer iframe').contentWindow.postMessage(JSON.stringify({ event: 'command', func: 'seekTo', args: [30, true] }), '*');
    }""")
    expect(page.locator(".watch-clock")).to_have_text("at 0:30")
    page.get_by_role("button", name="Analyse this moment").click()
    expect(page.get_by_role("textbox", name="Video time")).to_have_value("0:30")
    expect(page.locator(".frame-choice")).to_have_count(0)  # one fresh picture of what the player shows now
    page.get_by_role("button", name="Save observation").click()
    expect(page.get_by_text(re.compile(r"Observation #3 saved"))).to_be_visible()
    third = live_app.request("GET", "/api/observations/3")["snapshots"][0]
    assert colours_of(page, third["frame_image_url"])["middle"] == pytest.approx([255, 255, 255], abs=14), "as it is shown now"


def colours_of(page, address: str) -> dict:
    """Colours at a few places of a stored picture: its edges, its middle, and either side of the red block's edge."""
    return page.evaluate("""async (address) => {
        const bitmap = await createImageBitmap(await (await fetch(address)).blob());
        const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
        const pen = canvas.getContext('2d');
        pen.drawImage(bitmap, 0, 0);
        const at = (x, y) => Array.from(pen.getImageData(Math.floor(bitmap.width * x), Math.floor(bitmap.height * y), 1, 1).data.slice(0, 3));
        return { edges: [at(0.5, 0.004), at(0.5, 0.996), at(0.003, 0.5), at(0.997, 0.5)], middle: at(0.5, 0.5),
                 outsideRed: [at(0.24, 0.5), at(0.5, 0.235)], insideRed: [at(0.26, 0.5), at(0.5, 0.265)] };
    }""", address)
