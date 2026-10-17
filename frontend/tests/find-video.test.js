// Finding the video inside a shared picture of the screen: by the marks beside the app's own player,
// or by movement for a match playing in another window; and telling when it was paused.
// The pictures here are built by hand, pixel by pixel, so the expected answer is known exactly.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  Activity, MARK, PauseWatch, changes, chooseFrames, cropGrey, findMarkers, motionKind, movingArea, overlap, toGrey,
  videoRect,
} from '../js/watch/find-video.js';

const MAGENTA = [255, 0, 255];
const CYAN = [0, 255, 255];

/** A colour picture filled with one colour, with helpers to paint rectangles on it. */
function picture(width, height, fill = [22, 38, 63]) {
  const data = new Uint8ClampedArray(width * height * 4);
  const paint = (x, y, w, h, [r, g, b]) => {
    for (let row = y; row < y + h; row += 1) {
      for (let column = x; column < x + w; column += 1) data.set([r, g, b, 255], (row * width + column) * 4);
    }
  };
  paint(0, 0, width, height, fill);
  return { data, width, height, paint };
}

/** Paint the marks around a video at (x, y, w, h), as the page would show them at `scale` pixels per CSS pixel. */
function mark(image, video, scale, colours = [MAGENTA, CYAN]) {
  const half = (MARK.width / 2) * scale;
  const tall = MARK.height * scale;
  const [first, second] = colours;
  const top = video.y - (MARK.height + MARK.gap) * scale;
  image.paint(video.x, top, half, tall, first);
  image.paint(video.x + half, top, half, tall, second);
  const bottom = video.y + video.height + MARK.gap * scale;
  image.paint(video.x + video.width - 2 * half, bottom, half, tall, second);
  image.paint(video.x + video.width - half, bottom, half, tall, first);
}

// ── The marks ────────────────────────────────────────────────────────────────
test('the video is found exactly by its marks, whatever the zoom of the shared picture', () => {
  for (const scale of [1, 2, 3]) {
    const video = { x: 40 * scale, y: 120 * scale, width: 640 * scale, height: 360 * scale };
    const image = picture(800 * scale, 600 * scale);
    mark(image, video, scale);
    const marks = findMarkers(image.data, image.width, image.height);
    assert.deepEqual(videoRect(marks), video, `at ${scale} pixels per CSS pixel`);
  }
});

test('colours shifted by a wide-gamut screen are still recognised', () => {
  const video = { x: 100, y: 200, width: 1280, height: 720 };
  const image = picture(1600, 1100);
  mark(image, video, 2, [[234, 51, 251], [117, 251, 253]]);  // magenta and cyan as a Display P3 screen reports them
  assert.deepEqual(videoRect(findMarkers(image.data, image.width, image.height)), video);
});

test('colourful football pictures are not mistaken for the marks', () => {
  const video = { x: 60, y: 100, width: 640, height: 360 };
  const image = picture(800, 600);
  image.paint(60, 100, 640, 360, [46, 107, 78]);    // a pitch
  image.paint(200, 200, 40, 40, [255, 0, 255]);     // a magenta shirt: no cyan beside it
  image.paint(300, 250, 30, 6, [255, 0, 255]);      // magenta then cyan, but far too flat to be a mark
  image.paint(330, 250, 30, 6, [0, 255, 255]);
  mark(image, video, 1);
  assert.deepEqual(videoRect(findMarkers(image.data, image.width, image.height)), video);
});

test('with a mark missing, nothing is found rather than something guessed', () => {
  const image = picture(800, 600);
  assert.equal(findMarkers(image.data, image.width, image.height), null);  // no marks at all

  const half = (MARK.width / 2);
  image.paint(40, 110, half, MARK.height, MAGENTA);  // only the top-left mark: the video is partly out of view
  image.paint(40 + half, 110, half, MARK.height, CYAN);
  assert.equal(findMarkers(image.data, image.width, image.height), null);
});

test('marks too close together to hold a video are refused', () => {
  const image = picture(400, 300);
  mark(image, { x: 50, y: 50, width: 100, height: 40 }, 1);
  assert.equal(videoRect(findMarkers(image.data, image.width, image.height)), null);
});

// ── Grey pictures ────────────────────────────────────────────────────────────
test('grey values follow how bright each colour looks', () => {
  const image = picture(4, 1);
  image.paint(0, 0, 1, 1, [255, 255, 255]);
  image.paint(1, 0, 1, 1, [0, 0, 0]);
  image.paint(2, 0, 1, 1, [0, 255, 0]);
  image.paint(3, 0, 1, 1, [0, 0, 255]);
  assert.deepEqual([...toGrey(image.data)], [255, 0, 149, 28]);  // green looks far brighter than blue
});

test('a part of a grey picture is cut out exactly', () => {
  const whole = { grey: Uint8Array.from({ length: 20 }, (_, i) => i), width: 5, height: 4 };
  assert.deepEqual(cropGrey(whole, { x: 1, y: 2, width: 3, height: 2 }),
    { grey: Uint8Array.from([11, 12, 13, 16, 17, 18]), width: 3, height: 2 });
});

// ── A shared window, as the app sees it: a still page with a video somewhere in it ──
const WINDOW = { width: 400, height: 260 };
const VIDEO = { x: 60, y: 50, width: 256, height: 144 };

/** A grey "window": toolbar, text lines and a sidebar that never change, and a video area showing `scene(x, y)`. */
function windowPicture(scene, { video = VIDEO, extras = [] } = {}) {
  const { width, height } = WINDOW;
  const grey = new Uint8Array(width * height).fill(236);  // the page
  const box = (x, y, w, h, value) => {
    for (let row = y; row < y + h; row += 1) grey.fill(value, row * width + x, row * width + x + w);
  };
  box(0, 0, width, 24, 90);  // the browser's toolbar
  for (let line = 0; line < 6; line += 1) box(60, 205 + line * 9, 200 - line * 20, 4, 60);  // text under the video
  box(330, 50, 60, 140, 200);  // a sidebar
  for (let row = 0; row < video.height; row += 1) {
    for (let column = 0; column < video.width; column += 1) {
      grey[(video.y + row) * width + video.x + column] = scene(column, row);
    }
  }
  for (const extra of extras) extra(grey, width);
  return { grey, width, height };
}

/** A camera pan: a textured scene that slides along a little every picture, so every pixel keeps changing. */
const pan = (t) => (x, y) => (((x + t * 3) * 37) ^ (y * 53)) & 255;

/** Feed `count` pictures made by `make(t)` through an Activity, the way the app does while sharing. */
function watch(make, count = 14) {
  const activity = new Activity(WINDOW.width, WINDOW.height);
  let before = make(0);
  for (let t = 1; t <= count; t += 1) {
    const after = make(t);
    activity.add(changes(before, after));
    before = after;
  }
  return activity;
}

// The video's rectangle one pixel in from each side: a pixel on the very edge may be part page.
// A solid find is one where the whole picture moved, as it does when the camera follows the ball.
const inside = (rect) => ({ x: rect.x + 1, y: rect.y + 1, width: rect.width - 2, height: rect.height - 2, solid: true });

test('a playing video is found by its movement, and nothing of the page is taken with it', () => {
  const found = movingArea(watch((t) => windowPicture(pan(t))));
  assert.deepEqual(found, inside(VIDEO));
});

test('a part of the video that stands still, such as the score in a corner, stays inside the area', () => {
  const scene = (t) => (x, y) => (x < 50 && y < 16 ? 30 : pan(t)(x, y));  // a still scoreboard in the top-left corner
  assert.deepEqual(movingArea(watch((t) => windowPicture(scene(t)))), inside(VIDEO));
});

test('a black band inside the player is left out: only the moving picture is the video', () => {
  // A 4:3 match inside a 16:9 player: still black bands at the sides.
  const scene = (t) => (x, y) => (x < 32 || x >= 224 ? 0 : pan(t)(x, y));
  assert.deepEqual(movingArea(watch((t) => windowPicture(scene(t)))), inside({ x: VIDEO.x + 32, y: VIDEO.y, width: 192, height: 144 }));
});

test('a smaller moving thing elsewhere on the page, such as an animated advert, is not taken for the match', () => {
  const advert = (t) => (grey, width) => {
    for (let row = 205; row < 245; row += 1) {
      for (let column = 330; column < 390; column += 1) grey[row * width + column] = (column * 11 + t * 70) & 255;
    }
  };
  const found = movingArea(watch((t) => windowPicture(pan(t), { extras: [advert(t)] })));
  assert.deepEqual(found, inside(VIDEO));
});

test('with the camera still, the players moving over the grass are enough to find the video', () => {
  // Twelve players jogging across a still picture of grass; most of the grass never changes.
  const spots = [[12, 10], [60, 14], [120, 8], [190, 16], [236, 30], [30, 60], [100, 70], [170, 64],
    [228, 90], [20, 120], [90, 128], [160, 116]];
  const scene = (t) => (x, y) => (spots.some(([px, py]) => Math.abs(x - px - (t % 6) * 3) < 4 && Math.abs(y - py) < 6) ? 230 : 70);
  const found = movingArea(watch((t) => windowPicture(scene(t))));
  assert.ok(found, 'something was found');
  assert.equal(found.solid, false, 'a guess from scattered movement, which a solid find may replace');
  // All of it is video: nothing of the page around it.
  assert.ok(found.x >= VIDEO.x && found.y >= VIDEO.y && found.x + found.width <= VIDEO.x + VIDEO.width
    && found.y + found.height <= VIDEO.y + VIDEO.height, JSON.stringify(found));
  // And most of the video: the players reach close to its edges, so does the area.
  assert.ok(overlap(found, VIDEO) > 0.8, JSON.stringify(found));
});

test('nothing is found when nothing moves, or when only something tiny does', () => {
  assert.equal(movingArea(watch(() => windowPicture(() => 128))), null);  // a paused video: a still picture
  const cursor = (t) => (grey, width) => { grey[100 * width + 100] = t % 2 ? 0 : 255; };  // a blinking text cursor
  assert.equal(movingArea(watch((t) => windowPicture(() => 128, { extras: [cursor(t)] }))), null);
});

test('the video is found again after it moves, once the old place has stopped moving', () => {
  const moved = { x: 100, y: 80, width: 256, height: 144 };
  const activity = watch((t) => windowPicture(pan(t)));
  let before = windowPicture(pan(0), { video: moved });
  for (let t = 1; t <= 40; t += 1) {  // the page was scrolled; the match plays on in its new place
    const after = windowPicture(pan(t), { video: moved });
    activity.add(changes(before, after));
    before = after;
  }
  assert.deepEqual(movingArea(activity), inside(moved));
});

test('how much two rectangles overlap', () => {
  const a = { x: 0, y: 0, width: 10, height: 10 };
  assert.equal(overlap(a, a), 1);
  assert.equal(overlap(a, { x: 10, y: 0, width: 10, height: 10 }), 0);  // touching edges share nothing
  assert.equal(overlap(a, { x: 5, y: 0, width: 10, height: 10 }), 1 / 3);  // half of each, a third of both together
});

// ── Has it been paused? ──────────────────────────────────────────────────────
/** A grey picture of the video area alone. */
const area = (scene) => {
  const width = 160;
  const height = 90;
  const grey = new Uint8Array(width * height);
  for (let y = 0; y < height; y += 1) for (let x = 0; x < width; x += 1) grey[y * width + x] = scene(x, y);
  return { grey, width, height };
};

test('playing, paused, and a paused player that shows its buttons are told apart', () => {
  const frozen = area(pan(5));
  assert.equal(motionKind(frozen, area(pan(5))), 'still');
  assert.equal(motionKind(area(pan(5)), area(pan(6))), 'moving');  // the camera moved: everything changed

  // Paused, and the player's controls fade in along the bottom: one band changes.
  const controls = area((x, y) => (y > 78 ? 20 : pan(5)(x, y)));
  assert.equal(motionKind(frozen, controls), 'local');
  // Paused, and a pause symbol appears in the middle.
  const symbol = area((x, y) => (Math.abs(x - 80) < 8 && Math.abs(y - 45) < 8 ? 255 : pan(5)(x, y)));
  assert.equal(motionKind(frozen, symbol), 'local');

  // A quiet passage of play: a still camera, but players moving all over the pitch.
  const players = (t) => (x, y) => {
    for (const [px, py] of [[20, 15], [70, 20], [130, 30], [40, 50], [100, 60], [140, 80], [15, 80]]) {
      if (Math.abs(x - px - t * 3) < 3 && Math.abs(y - py) < 5) return 240;
    }
    return 90;  // grass
  };
  assert.equal(motionKind(area(players(0)), area(players(1))), 'moving');
});

test('a pause is reported after three pictures without movement, and play again after three with', () => {
  const watcher = new PauseWatch();
  const seen = (kinds, start) => kinds.map((kind, index) => watcher.add(kind, start + index * 200));

  assert.deepEqual(seen(['moving', 'moving', 'moving'], 0), [false, false, false]);
  assert.equal(watcher.paused, false);
  // The pause: the buttons fade in (local), then nothing changes.
  assert.deepEqual(seen(['local', 'still', 'still'], 600), [false, false, true]);
  assert.equal(watcher.paused, true);
  assert.equal(watcher.pausedAt, 600, 'paused from the first picture that stopped moving');

  // One moving picture (the controls disappearing, a mouse moving over it) is not enough to call it playing.
  assert.deepEqual(seen(['moving', 'local', 'moving', 'still'], 1200), [false, false, false, false]);
  assert.equal(watcher.paused, true);
  // Moved to another moment while paused: still paused, from then on.
  watcher.movedTo(1900);
  assert.equal(watcher.pausedAt, 1900);
  assert.deepEqual(seen(['moving', 'moving', 'moving'], 2000), [false, false, true]);
  assert.equal(watcher.paused, false);
  assert.equal(watcher.pausedAt, null);
  watcher.movedTo(2700);  // only a paused video can be moved while paused
  assert.equal(watcher.pausedAt, null);
});

// ── Which frame is offered first? ────────────────────────────────────────────
const frames = (...times) => times.map((at) => ({ at }));

test('while the match plays, the latest frame is chosen and the seconds before it are offered', () => {
  const kept = frames(0, 200, 400, 600, 800, 1000, 3000, 3200);
  assert.deepEqual(chooseFrames(kept, { end: 3200, span: 500 }), { offered: [6, 7], chosen: 7 });
  assert.deepEqual(chooseFrames(kept, { end: 1000, span: 500 }), { offered: [3, 4, 5], chosen: 5 });
});

test('after a pause, the frame from just before the player showed its buttons is chosen', () => {
  // Frames every 200 ms; the video stopped moving at 2000; its buttons may be in frames after 1400.
  const kept = frames(0, 200, 400, 600, 800, 1000, 1200, 1400, 1600, 1800, 2000);
  const choice = chooseFrames(kept, { end: 2000, avoidAfter: 1400 });
  assert.equal(choice.chosen, 7);
  assert.deepEqual(choice.offered, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 'the paused picture itself is offered too');
  // When every kept frame is too late, the earliest is the best guess.
  assert.deepEqual(chooseFrames(frames(1500, 1700), { end: 1700, avoidAfter: 1000 }), { offered: [0, 1], chosen: 0 });
  assert.equal(chooseFrames([], { end: 0 }), null);
});
