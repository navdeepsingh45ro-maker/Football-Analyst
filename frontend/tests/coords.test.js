// Acceptance test F: resize the display and the annotations stay on their spot.
//
// These tests exercise the exact functions the editor uses for every mouse
// position (clientToView) and that mirror how the browser places the drawing
// (viewToClient). A "rect" below is what getBoundingClientRect() would return
// for the drawing surface at some window size.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { FrameSpace, PitchSpace, clientToView, fit, viewToClient } from '../js/editor/coords.js';

const near = (actual, expected, message) => assert.ok(Math.abs(actual - expected) < 1e-9, `${message}: ${actual} vs ${expected}`);

/** Where the picture really is inside the element, worked out independently of coords.js. */
function pictureBox(rect, width, height) {
  const scale = Math.min(rect.width / width, rect.height / height);
  const shownWidth = width * scale;
  const shownHeight = height * scale;
  return {
    left: rect.left + (rect.width - shownWidth) / 2,
    top: rect.top + (rect.height - shownHeight) / 2,
    width: shownWidth,
    height: shownHeight,
  };
}

// The same surface at different window sizes, scroll positions and shapes.
const LAYOUTS = [
  { name: 'desktop, exact 16:9', rect: { left: 40, top: 120, width: 1280, height: 720 } },
  { name: 'half size', rect: { left: 12, top: 300, width: 640, height: 360 } },
  { name: 'odd size', rect: { left: 7.5, top: 61.25, width: 913, height: 513.5625 } },
  { name: 'phone width', rect: { left: 0, top: 480, width: 360, height: 202.5 } },
  { name: 'zoomed in', rect: { left: -200, top: -90, width: 2560, height: 1440 } },
  { name: 'box too wide (bands left and right)', rect: { left: 10, top: 10, width: 1600, height: 450 } },
  { name: 'box too tall (bands above and below)', rect: { left: 10, top: 10, width: 500, height: 900 } },
];

const FRAME_SIZES = [[1280, 720], [1920, 1080], [3840, 2160], [640, 480], [720, 1280], [1000, 1000]];
const STORED_POINTS = [[0.512, 0.431], [0, 0], [1, 1], [0.25, 0.9], [0.999, 0.001]];

test('a stored frame point is drawn on the same spot of the picture at every display size', () => {
  for (const [width, height] of FRAME_SIZES) {
    const space = new FrameSpace(width, height);
    for (const layout of LAYOUTS) {
      const picture = pictureBox(layout.rect, width, height);
      for (const stored of STORED_POINTS) {
        const [screenX, screenY] = viewToClient(space.toView(stored), layout.rect, space.view);
        // The point sits the same FRACTION of the way across and down the picture, always.
        near((screenX - picture.left) / picture.width, stored[0], `${width}x${height} ${layout.name} x`);
        near((screenY - picture.top) / picture.height, stored[1], `${width}x${height} ${layout.name} y`);
      }
    }
  }
});

test('a click is stored as the same point whatever the display size', () => {
  for (const [width, height] of FRAME_SIZES) {
    const space = new FrameSpace(width, height);
    for (const layout of LAYOUTS) {
      for (const stored of STORED_POINTS) {
        const screen = viewToClient(space.toView(stored), layout.rect, space.view);
        const back = space.fromView(clientToView(screen, layout.rect, space.view));
        near(back[0], stored[0], `${layout.name} x`);
        near(back[1], stored[1], `${layout.name} y`);
      }
    }
  }
});

test('resizing the window between drawing and viewing keeps a marker on its player', () => {
  const space = new FrameSpace(1280, 720);
  const whenDrawn = LAYOUTS[0].rect;
  // The analyst clicks on a player who is 600 px across and 300 px down the picture as displayed.
  const click = [whenDrawn.left + 600, whenDrawn.top + 300];
  const stored = space.fromView(clientToView(click, whenDrawn, space.view));
  assert.deepEqual(stored, [600 / 1280, 300 / 720]);  // a fraction of the frame, not a screen position

  for (const layout of LAYOUTS.slice(1)) {
    const picture = pictureBox(layout.rect, 1280, 720);
    const [screenX, screenY] = viewToClient(space.toView(stored), layout.rect, space.view);
    // The player is still 600/1280 across and 300/720 down the (now differently sized) picture,
    // and that is exactly where the marker is drawn.
    near(screenX, picture.left + picture.width * (600 / 1280), `${layout.name} x`);
    near(screenY, picture.top + picture.height * (300 / 720), `${layout.name} y`);
  }
});

test('the picture is never stretched: one scale for both directions, spare space split evenly', () => {
  const view = { x: 0, y: 0, width: 1280, height: 720 };
  const wide = fit({ width: 1600, height: 450 }, view);
  near(wide.scale, 450 / 720, 'wide box is limited by its height');
  near(wide.offsetX, (1600 - 1280 * wide.scale) / 2, 'equal bands left and right');
  near(wide.offsetY, 0, 'no bands above or below');

  const tall = fit({ width: 500, height: 900 }, view);
  near(tall.scale, 500 / 1280, 'tall box is limited by its width');
  near(tall.offsetX, 0, 'no bands left or right');
  near(tall.offsetY, (900 - 720 * tall.scale) / 2, 'equal bands above and below');
});

test('a click in the empty band beside the picture is pulled back inside the frame', () => {
  const space = new FrameSpace(1280, 720);
  const rect = { left: 10, top: 10, width: 1600, height: 450 };  // bands on the left and right
  const inLeftBand = space.fromView(clientToView([15, 200], rect, space.view));
  assert.ok(inLeftBand[0] < 0, 'raw conversion is outside the frame');
  assert.deepEqual(space.tidy(inLeftBand)[0], 0);
  assert.deepEqual(space.tidy([1.4, -0.2]), [1, 0]);
});

test('pitch positions are metres and survive any display size', () => {
  const space = new PitchSpace(105, 68);
  assert.deepEqual(space.view, { x: -4, y: -4, width: 113, height: 76 });
  for (const layout of LAYOUTS) {
    for (const metres of [[0, 0], [105, 68], [52.5, 34], [94, 34], [78, 30.5], [-2, 70]]) {
      const screen = viewToClient(space.toView(metres), layout.rect, space.view);
      const back = space.fromView(clientToView(screen, layout.rect, space.view));
      near(back[0], metres[0], `${layout.name} x`);
      near(back[1], metres[1], `${layout.name} y`);
    }
  }
  // The centre spot is drawn in the middle of the surface.
  const rect = { left: 0, top: 0, width: 1130, height: 760 };
  assert.deepEqual(viewToClient(space.toView([52.5, 34]), rect, space.view), [565, 380]);
  // A marker cannot be dragged further than the strip around the pitch, and is kept to the centimetre.
  assert.deepEqual(space.tidy([200, -50]), [109, -4]);
  assert.deepEqual(space.tidy([78.123456, 30.987654]), [78.12, 30.99]);
});

test('frame coordinates and pitch coordinates are different systems', () => {
  const rect = { left: 0, top: 0, width: 1130, height: 760 };
  const frame = new FrameSpace(1280, 720);
  const pitch = new PitchSpace(105, 68);
  // The same two numbers mean "the middle of the picture" on a frame ...
  const onFrame = viewToClient(frame.toView([0.5, 0.5]), { left: 0, top: 0, width: 1280, height: 720 }, frame.view);
  assert.deepEqual(onFrame, [640, 360]);
  // ... and "half a metre from the corner flag" on the pitch.
  const onPitch = viewToClient(pitch.toView([0.5, 0.5]), rect, pitch.view);
  assert.deepEqual(onPitch, [45, 45]);
  assert.equal(frame.layer, 'frame');
  assert.equal(pitch.layer, 'pitch');
});

test('markers are sized relative to the picture, so they look the same at 720p and 4K', () => {
  assert.equal(new FrameSpace(1280, 720).unit / 1280, new FrameSpace(3840, 2160).unit / 3840);
  // An arrow-key press moves a shape the same number of frame pixels in both directions.
  const space = new FrameSpace(1280, 720);
  near(space.step[0] * 1280, space.step[1] * 720, 'equal pixel step');
});
