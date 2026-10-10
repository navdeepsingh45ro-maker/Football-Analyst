// Coordinate systems, and the conversions between them.
//
// FOUR DIFFERENT SPACES ARE INVOLVED WHEN YOU DRAW. They are not interchangeable:
//
//   1. SCREEN (client) pixels   where the mouse is: event.clientX / clientY.
//                               Changes whenever the window is resized or scrolled.
//                               NEVER STORED.
//
//   2. VIEW units               the drawing's own fixed coordinate system: the
//                               `viewBox` of the SVG. For a video frame it is the
//                               frame's real size in pixels (e.g. 1280 x 720); for
//                               the pitch it is metres. The browser scales the view
//                               to whatever size the element has on screen.
//
//   3. STORED frame coordinates fractions of the frame, 0 to 1 in each direction.
//                               (0.5, 0.5) is the middle of the picture whatever
//                               its resolution and however large it is displayed.
//
//   4. STORED pitch coordinates metres on the pitch (see geometry.js).
//
// A mouse position travels:  screen --clientToView--> view --space.fromView--> stored.
// Drawing goes the other way: stored --space.toView--> view, and the browser does
// view -> screen. Because only (3) and (4) are ever saved, a diagram lines up again
// at any window size, zoom level or screen. frontend/tests/coords.test.js proves it.

/**
 * How a view is fitted into an element: as large as possible, centred, and never
 * stretched (this is what the SVG attribute preserveAspectRatio="xMidYMid meet" does).
 * If the element is the wrong shape, the spare space becomes equal bands on two sides.
 */
export function fit(box, view) {
  const scale = Math.min(box.width / view.width, box.height / view.height);
  return {
    scale,                                              // screen pixels per view unit
    offsetX: (box.width - view.width * scale) / 2,      // width of the left band
    offsetY: (box.height - view.height * scale) / 2,    // height of the top band
  };
}

/** Screen position -> view coordinates. `rect` is the element's getBoundingClientRect(). */
export function clientToView(client, rect, view) {
  const { scale, offsetX, offsetY } = fit(rect, view);
  return [
    view.x + (client[0] - rect.left - offsetX) / scale,
    view.y + (client[1] - rect.top - offsetY) / scale,
  ];
}

/** View coordinates -> screen position (the exact reverse of clientToView). */
export function viewToClient(point, rect, view) {
  const { scale, offsetX, offsetY } = fit(rect, view);
  return [
    rect.left + offsetX + (point[0] - view.x) * scale,
    rect.top + offsetY + (point[1] - view.y) * scale,
  ];
}

const clampNumber = (value, low, high) => Math.min(high, Math.max(low, value));
const roundTo = (value, decimals) => Number(value.toFixed(decimals));

/** The coordinate system of a video frame (or screenshot) of a known pixel size. */
export class FrameSpace {
  constructor(width, height) {
    this.layer = 'frame';
    this.width = width;
    this.height = height;
    this.view = { x: 0, y: 0, width, height };
    // One "unit" is 1/80 of the longer side. Markers and line widths are sized in
    // units, so they look the same on a 720p frame and on a 4K frame.
    this.unit = Math.max(width, height) / 80;
    // How far one press of an arrow key moves a shape: half a unit, in each direction.
    this.step = [this.unit / 2 / width, this.unit / 2 / height];
  }

  toView([x, y]) { return [x * this.width, y * this.height]; }

  fromView([vx, vy]) { return [vx / this.width, vy / this.height]; }

  /** Keep a point inside the frame and trim it to a sensible precision. */
  tidy([x, y]) { return [roundTo(clampNumber(x, 0, 1), 5), roundTo(clampNumber(y, 0, 1), 5)]; }

  describe([x, y]) { return `${Math.round(x * 100)}% across, ${Math.round(y * 100)}% down the picture`; }
}

/** The coordinate system of the top-down pitch, in metres. */
export class PitchSpace {
  constructor(length = 105, width = 68, margin = 4) {
    this.layer = 'pitch';
    this.length = length;
    this.width = width;
    this.margin = margin;  // strip shown around the pitch, where a marker may also sit
    this.view = { x: -margin, y: -margin, width: length + 2 * margin, height: width + 2 * margin };
    // Sets how big markers and lines are drawn: a marker is about 4 m across. That
    // is larger than a real player, on purpose, like the magnets on a tactics board.
    this.unit = 1.5;
    this.step = [0.5, 0.5];  // half a metre per arrow-key press
  }

  // View units ARE metres here, so the two conversions do nothing. They exist so
  // the rest of the editor can treat both kinds of surface the same way.
  toView(point) { return [point[0], point[1]]; }

  fromView(point) { return [point[0], point[1]]; }

  /** Keep a point on (or just beside) the pitch and round it to the centimetre. */
  tidy([x, y]) {
    return [
      roundTo(clampNumber(x, -this.margin, this.length + this.margin), 2),
      roundTo(clampNumber(y, -this.margin, this.width + this.margin), 2),
    ];
  }

  describe([x, y]) {
    return `${x.toFixed(1)} m from own goal line, ${y.toFixed(1)} m from the left touchline`;
  }
}
