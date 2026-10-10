// Finding the video inside a shared picture of the screen, from the two corner marks.
// The pictures here are built by hand, pixel by pixel, so the expected answer is known exactly.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { MARK, findMarkers, videoRect } from '../js/editor/screen-capture.js';

const MAGENTA = [255, 0, 255];
const CYAN = [0, 255, 255];

/** A picture filled with one colour, with helpers to paint rectangles on it. */
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

test('the video is found exactly, whatever the zoom of the shared picture', () => {
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
