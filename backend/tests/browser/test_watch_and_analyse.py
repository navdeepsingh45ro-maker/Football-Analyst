"""Watching and analysing at the same time: the analysis desk, in a real browser.

  - a match on any website, watched in its own window: the app finds the video in the shared
    window, notices a pause, and takes the frame from just before it (the player's pause
    symbol is not on it)
  - marking the video by hand
  - the keys, and what happens to an unsaved moment when Analyse is pressed again
  - changing a saved moment without leaving the video
  - the bar that shares the room between the video and the drawing
"""
import re

import pytest
from playwright.sync_api import expect

from tests.browser.test_analysis_workflow import (  # noqa: F401  (scene is a fixture used by name)
    BALL, DEFENDER, FRAME, PITCH, click_on, pitch, scene, tool, video_state, wait_until,
)

LINK = "https://broadcaster.example/watch/full-match"

# What the browser would hand over after you agree to share another window: a picture of a web
# page with a match playing in it. The headless test browser cannot share a real window, so this
# paints one, 1600 x 1000: a still page (toolbar, lines of text) and, at (200, 180), a 960 x 540
# video in which the "camera" moves all the time: coloured stripes, never grey, changing every
# picture. window.standIn.pause() freezes the match and covers it the way players do when paused:
# a white play symbol in the middle and a dark bar along the bottom. window.standIn.play() resumes,
# and window.standIn.jump() moves the paused match on to another moment, as dragging its slider does.
# With window.standIn.advert = true, an animated 300 x 250 advert keeps changing beside the video.
# It is set on MediaDevices.prototype because Safari's engine may hand the page a new
# navigator.mediaDevices (it does after a window has been opened), which would not have it.
MATCH_WINDOW_STAND_IN = """
MediaDevices.prototype.getDisplayMedia = async () => {
  const canvas = document.createElement('canvas');
  canvas.width = 1600;
  canvas.height = 1000;
  const pen = canvas.getContext('2d');
  const video = { x: 200, y: 180, width: 960, height: 540 };
  let t = 0;
  let paused = false;
  window.standIn = { video, advert: false, pause() { paused = true; }, play() { paused = false; }, jump() { t += 40; } };
  let advertTick = 0;
  const paint = () => {
    pen.fillStyle = 'rgb(236,236,236)'; pen.fillRect(0, 0, 1600, 1000);
    pen.fillStyle = 'rgb(90,90,90)'; pen.fillRect(0, 0, 1600, 70);
    pen.fillStyle = 'rgb(60,60,60)';
    for (let line = 0; line < 6; line += 1) pen.fillRect(200, 760 + line * 28, 700 - line * 60, 12);
    if (!paused) t += 1;
    for (let x = 0; x < video.width; x += 40) {
      pen.fillStyle = `hsl(${(x + t * 13) % 360}, 70%, ${30 + ((x * 7 + t * 11) % 40)}%)`;
      pen.fillRect(video.x + x, video.y, 40, video.height);
    }
    if (window.standIn.advert) {
      advertTick += 1;
      for (let x = 0; x < 300; x += 25) {
        pen.fillStyle = (x / 25 + advertTick) % 2 ? 'rgb(20,20,200)' : 'rgb(240,220,0)';
        pen.fillRect(1250 + x, 200, 25, 250);
      }
    }
    if (paused) {
      pen.fillStyle = 'rgb(255,255,255)';
      pen.beginPath(); pen.moveTo(640, 400); pen.lineTo(640, 500); pen.lineTo(720, 450); pen.fill();
      pen.fillStyle = 'rgba(0,0,0,0.6)'; pen.fillRect(video.x, video.y + video.height - 50, video.width, 50);
    }
  };
  paint();
  setInterval(paint, 40);
  return canvas.captureStream(25);
};
"""


def colours(page, address: str, points: list[tuple[float, float]]) -> list[list[int]]:
    """The colours of a picture (a blob: or stored address) at points given as fractions of its width and height.

    The picture is loaded the way the page shows pictures, as an image: the app's Content-Security-Policy
    rightly does not let a page fetch() a blob: address.
    """
    return page.evaluate("""async ([address, points]) => {
        const image = new Image();
        image.src = address;
        await image.decode();
        const canvas = document.createElement('canvas');
        canvas.width = image.naturalWidth;
        canvas.height = image.naturalHeight;
        const pen = canvas.getContext('2d');
        pen.drawImage(image, 0, 0);
        return points.map(([x, y]) => Array.from(pen.getImageData(Math.floor(canvas.width * x), Math.floor(canvas.height * y), 1, 1).data.slice(0, 3)));
    }""", [address, points])


def is_match_colour(colour: list[int]) -> bool:
    """The stand-in's match is all strong colours; the page around it is grey (all three channels alike)."""
    return max(colour) - min(colour) > 40


def drawing_picture(page) -> str:
    return page.locator(f"{FRAME} image").get_attribute("href")


@pytest.fixture
def broadcast(page, live_app):
    """A match whose video is a link to some website, and the stand-in for sharing the window it plays in."""
    player = live_app.request("POST", "/api/players", {"full_name": "Sam Finisher"})
    match = live_app.request("POST", "/api/matches", {"home_team": "Northside FC", "away_team": "Riverton United"})
    video = live_app.request("POST", f"/api/matches/{match['id']}/videos", {"location": LINK})
    assert video["playback"]["mode"] == "window"
    page.context.route("https://broadcaster.example/**", lambda route: route.fulfill(content_type="text/html", body="<title>The match</title>"))
    page.add_init_script(MATCH_WINDOW_STAND_IN)
    return {"player": player, "match": match, "video": video}


def test_a_match_on_any_website_is_analysed_from_its_own_window(page, live_app, broadcast):
    page.goto(f"{live_app.url}/video.html?match={broadcast['match']['id']}")
    expect(page.get_by_text("Watch the match in its own window")).to_be_visible()
    # Before a window is shared there is nothing to take a picture of: the steps, not the button.
    expect(page.get_by_role("button", name="Analyse this moment")).to_be_hidden()

    # ── The match opens in a window of its own ───────────────────────────────
    with page.context.expect_page() as opened:
        page.get_by_role("button", name="Open the match link").click()
    match_window = opened.value
    match_window.wait_for_load_state()
    assert match_window.url == LINK
    match_window.close()

    # ── Connect it: the app finds the moving video in what is shared ─────────
    page.get_by_role("button", name="Connect the match window").click()
    expect(page.get_by_text("Looking for the video in the shared window")).to_be_visible()
    expect(page.locator(".chip-state")).to_have_text("Playing", timeout=15000)
    page.snap("1-found")

    # ── Analyse while it plays: the latest frame, the video and nothing else ─
    page.get_by_role("button", name="Analyse this moment").click()
    expect(page.locator(".frame-choice[aria-pressed='true']")).to_have_text("now")
    expect(page.get_by_role("textbox", name="Video time")).to_have_value("")  # the app cannot read that player's time
    expect(page.locator(".draft-head")).to_contain_text("Type the time shown in the match's own player")
    page.get_by_role("textbox", name="Video time").fill("12:34")
    page.get_by_label("Add another player by name").fill("Sam Finisher")
    page.get_by_label("Add another player by name").press("Enter")
    page.get_by_role("button", name="Save observation").click()
    expect(page.get_by_text(re.compile(r"Observation #1 saved"))).to_be_visible()

    first = live_app.request("GET", "/api/observations/1")
    assert first["video_reference_id"] == broadcast["video"]["id"]
    assert first["video_time_seconds"] == 754
    snapshot = first["snapshots"][0]
    assert snapshot["frame_source"] == "video_capture"
    # The stand-in's video is 960 x 540. A few pixels may be left off its edges, never page added to them.
    assert 930 <= snapshot["frame_width"] <= 960 and 510 <= snapshot["frame_height"] <= 540, snapshot
    assert snapshot["frame_width"] / snapshot["frame_height"] == pytest.approx(960 / 540, rel=0.02)
    edges = colours(page, snapshot["frame_image_url"], [(0.5, 0.004), (0.5, 0.996), (0.003, 0.5), (0.997, 0.5), (0.003, 0.004), (0.997, 0.996)])
    assert all(is_match_colour(colour) for colour in edges), edges

    # ── Paused there: its pause symbol covers the middle; Analyse takes the frame from before ──
    page.evaluate("() => window.standIn.pause()")
    expect(page.locator(".chip-state")).to_have_text("Paused")
    page.get_by_role("button", name="Analyse this moment").click()
    chosen = page.locator(".frame-choice[aria-pressed='true']")
    expect(chosen).to_contain_text("s earlier")
    page.snap("2-paused-and-analysed")
    [middle] = colours(page, drawing_picture(page), [(0.5, 0.5)])
    assert is_match_colour(middle), f"the middle should be the match, not the white pause symbol: {middle}"

    # The paused picture itself is offered last, for a player that shows nothing over it.
    last = page.locator(".frame-choice").last
    expect(last).to_have_text("when paused")
    last.click()
    expect(last).to_have_attribute("aria-pressed", "true")
    [middle] = colours(page, drawing_picture(page), [(0.5, 0.5)])
    assert min(middle) > 220, f"the paused picture has the white symbol in the middle: {middle}"

    # ── Moved on while paused, to look again: Analyse takes what it shows now ─
    shown = drawing_picture(page)
    before = colours(page, shown, [(0.1, 0.3), (0.3, 0.3), (0.7, 0.3)])
    page.evaluate("() => window.standIn.jump()")
    page.wait_for_timeout(1000)
    page.get_by_role("button", name="Analyse this moment").click()
    expect(page.locator(".frame-choice")).to_have_count(0)  # one picture: the moment it was moved to
    expect(page.locator(f"{FRAME} image")).not_to_have_attribute("href", shown)
    after = colours(page, drawing_picture(page), [(0.1, 0.3), (0.3, 0.3), (0.7, 0.3)])
    assert after != before, "the picture is of the moment the match was moved to"
    [middle] = colours(page, drawing_picture(page), [(0.5, 0.5)])
    assert min(middle) > 220, "taken as it is shown, paused, with the symbol"


def test_an_advert_that_keeps_moving_while_the_match_is_paused_is_not_taken_for_it(page, live_app, broadcast):
    page.goto(f"{live_app.url}/video.html?match={broadcast['match']['id']}")
    page.get_by_role("button", name="Connect the match window").click()
    page.evaluate("() => { window.standIn.advert = true; }")
    expect(page.locator(".chip-state")).to_have_text("Playing", timeout=15000)

    page.evaluate("() => window.standIn.pause()")
    expect(page.locator(".chip-state")).to_have_text("Paused")
    page.wait_for_timeout(6000)  # long enough for the paused match to stop counting as moving; the advert goes on
    page.get_by_role("button", name="Analyse this moment").click()
    expect(page.locator(FRAME)).to_be_visible()
    size = page.locator(".surface-box[data-layer='frame'] .surface-title span").text_content()
    assert size.startswith(("95", "96", "94")), f"still the match's 960 x 540, not the 300 x 250 advert: {size}"
    [middle] = colours(page, drawing_picture(page), [(0.5, 0.5)])
    assert is_match_colour(middle) and min(middle) < 220, f"the match from before the pause: {middle}"


def test_the_video_can_be_marked_by_hand(page, live_app, broadcast):
    page.goto(f"{live_app.url}/video.html?match={broadcast['match']['id']}")
    page.get_by_role("button", name="Connect the match window").click()
    page.get_by_role("button", name="Mark the video by hand").click()

    # Drag across the left half of the video, on the still of the whole shared window.
    view = page.locator(".mark-view")
    box = view.bounding_box()
    at = lambda x, y: (box["x"] + box["width"] * x / 1600, box["y"] + box["height"] * y / 1000)  # noqa: E731
    page.mouse.move(*at(200, 180))
    page.mouse.down()
    page.mouse.move(*at(440, 450))
    page.mouse.move(*at(680, 720))
    page.mouse.up()
    expect(page.get_by_text("The video is marked.")).to_be_visible()
    expect(page.get_by_role("button", name="Find the video automatically")).to_be_visible()

    page.wait_for_timeout(600)  # a few pictures of the marked area are kept
    page.get_by_role("button", name="Analyse this moment").click()
    expect(page.locator(FRAME)).to_be_visible()
    size = page.locator(".surface-box[data-layer='frame'] .surface-title span").text_content()
    width, height = (int(number) for number in re.match(r"(\d+) × (\d+)", size).groups())
    # 480 x 540 of the shared picture, give or take what one screen pixel of the drag stands for.
    assert width == pytest.approx(480, abs=8) and height == pytest.approx(540, abs=8), size


def test_keys_and_a_second_moment_before_the_first_is_saved(page, live_app, scene):
    page.goto(f"{live_app.url}/video.html?match={scene['match']['id']}")
    wait_until(page, "() => { const v = document.querySelector('video'); return Boolean(v) && v.readyState >= 1; }")
    page.evaluate("() => { const v = document.querySelector('video'); v.muted = true; return v.play(); }")
    wait_until(page, "() => document.querySelector('video').currentTime > 1.2")

    # ── A: analyse this moment ───────────────────────────────────────────────
    page.locator("h1").click()  # the keyboard belongs to the page, not to a box
    page.keyboard.press("a")
    expect(page.locator(FRAME)).to_be_visible()
    first_time = page.get_by_role("textbox", name="Video time").input_value()
    assert video_state(page)["paused"] is True

    # ── K: play on while the moment keeps its own time; K again to pause ─────
    page.keyboard.press("k")
    wait_until(page, "() => !document.querySelector('video').paused && document.querySelector('video').currentTime > 2.2")
    assert page.get_by_role("textbox", name="Video time").input_value() == first_time
    page.keyboard.press("k")
    wait_until(page, "() => document.querySelector('video').paused")

    # ── J and L: back and forward five seconds, within the video ─────────────
    page.keyboard.press("j")
    wait_until(page, "() => document.querySelector('video').currentTime === 0")  # the clip is only six seconds long
    page.keyboard.press("l")
    wait_until(page, "() => Math.abs(document.querySelector('video').currentTime - 5) < 0.01")

    # ── Analyse again while the first moment has unsaved drawing: asked first ─
    tool(page, BALL)
    click_on(page, FRAME, (0.5, 0.5))
    page.locator("h1").click()
    page.keyboard.press("a")
    question = page.get_by_role("dialog")
    expect(question).to_contain_text("You have not saved the moment at")
    question.get_by_role("button", name="Save it first").click()
    expect(page.get_by_text(re.compile(r"Observation #1 saved"))).to_be_visible()
    expect(page.get_by_role("textbox", name="Video time")).to_have_value("0:05")  # the new moment's own time

    # ── Cmd/Ctrl + S saves, even while typing ───────────────────────────────
    page.get_by_label("Your interpretation").fill("Second look at it.")
    page.keyboard.press("Control+s")
    expect(page.get_by_text(re.compile(r"Observation #2 saved"))).to_be_visible()

    first = live_app.request("GET", "/api/observations/1")
    second = live_app.request("GET", "/api/observations/2")
    assert first["video_time_seconds"] > 1.2 and [a["kind"] for a in first["snapshots"][0]["annotations"]] == ["ball"]
    assert second["video_time_seconds"] == pytest.approx(5, abs=0.01)
    assert second["notes"] == "Second look at it."


def test_a_saved_moment_is_changed_beside_the_video(page, live_app, scene):
    created = live_app.request("POST", "/api/observations", {
        "player_ids": [scene["striker"]["id"]], "match_id": scene["match"]["id"],
        "video_reference_id": scene["video"]["id"], "video_time_seconds": 2.5, "category": "Positioning",
        "snapshot": {"annotations": [{"uid": "ball-1", "layer": "pitch", "kind": "ball", "points": [[60, 30]]}]}})
    address = f"{live_app.url}/video.html?match={scene['match']['id']}"
    page.goto(address)
    page.locator(".desk-moments").get_by_role("link", name="Positioning").click()
    page.get_by_role("dialog").get_by_role("button", name="Edit drawing").click()

    expect(page.locator(".draft-head h2")).to_have_text(f"Editing observation #{created['id']}")
    expect(page.locator(f'{PITCH} g[data-kind="ball"]')).to_have_count(1)
    expect(page.locator("video")).to_be_visible()  # still beside the video
    tool(page, DEFENDER)
    click_on(page, PITCH, pitch(70, 40))
    page.get_by_role("button", name="Save changes").click()
    expect(page.get_by_text(f"Observation #{created['id']} saved")).to_be_visible()
    expect(page.locator(".draft-head h2")).to_have_text("New moment")
    assert page.url == address  # never left the page

    after = live_app.request("GET", f"/api/observations/{created['id']}")
    assert sorted(a["kind"] for a in after["snapshots"][0]["annotations"]) == ["ball", "defender"]
    assert live_app.request("GET", "/api/observations")["total"] == 1


def test_the_bar_between_the_video_and_the_drawing_shares_out_the_room(page, live_app, scene):
    page.goto(f"{live_app.url}/video.html?match={scene['match']['id']}")
    handle = page.get_by_role("separator", name="Give the video or the drawing more room")
    before = page.locator(".desk-viewer").bounding_box()["width"]

    box = handle.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 200)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] / 2 + 100, box["y"] + 200)
    page.mouse.move(box["x"] + box["width"] / 2 + 200, box["y"] + 200)
    page.mouse.up()
    wider = page.locator(".desk-viewer").bounding_box()["width"]
    assert wider == pytest.approx(before + 200, abs=6)

    handle.focus()
    share = int(handle.get_attribute("aria-valuenow"))
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("ArrowLeft")
    assert int(handle.get_attribute("aria-valuenow")) == share - 4

    page.reload()  # remembered
    expect(handle).to_have_attribute("aria-valuenow", str(share - 4))
