// Finding the match video inside a shared picture of the screen, and telling when it is paused.
//
// When you share a window or the screen with the app (screen-share.js), the app
// receives a moving picture of everything in it: the browser's toolbar, the web
// page around the video, the video itself. The functions here answer three
// questions about that picture:
//
//   WHERE IS THE VIDEO?
//     The app's own YouTube player     by two small marks the page shows beside its corners
//                                      (findMarkers, videoRect)
//     a match playing in another window by movement: a web page stands still, a football
//                                      match never does (Activity, movingArea)
//
//   HAS IT BEEN PAUSED?
//     When the video area stops changing all over (motionKind). A paused player still
//     changes in one place or a band: its buttons fade in, the mouse moves over it. A
//     playing match changes across the whole picture.
//
//   WHICH FRAME SHOULD BE OFFERED?
//     The one from just before the pause, because a paused player covers the picture
//     with its own buttons (chooseFrames).
//
// They work on small grey copies of the picture (a few hundred pixels across) and
// are pure functions, so `npm test` checks them without a browser
// (frontend/tests/find-video.test.js).

// ── The marks beside the app's own player ───────────────────────────────────
// While one-click pictures are on, the page shows two tiny two-coloured marks just
// outside the corners of its YouTube player:
//
//     [magenta|cyan]  above the top-left corner
//     [cyan|magenta]  below the bottom-right corner
//
// Their size and position in CSS pixels. Must match .capture-mark in css/app.css.
export const MARK = { width: 16, height: 8, gap: 2 };

// Colours are judged loosely: a wide-gamut screen shifts them on their way through the capture.
const isMagenta = (r, g, b) => r > 160 && b > 160 && g < 130 && Math.min(r, b) - g > 70;
const isCyan = (r, g, b) => g > 160 && b > 160 && r < 160 && Math.min(g, b) - r > 70;

/**
 * Find the two marks in a picture.
 *   data            RGBA bytes, row by row (what canvas getImageData() returns)
 * Returns { topLeft, bottomRight }, each { x, y, width, height } in picture pixels, or null if either is missing.
 */
export function findMarkers(data, width, height) {
  const at = (x, y, test) => {
    const i = (y * width + x) * 4;
    return test(data[i], data[i + 1], data[i + 2]);
  };
  const run = (x, y, test) => {
    let length = 0;
    while (x + length < width && at(x + length, y, test)) length += 1;
    return length;
  };

  /** The first place where a run of `first` is followed at once by an equally long run of `second`. */
  function find(first, second) {
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        if (!at(x, y, first) || (x > 0 && at(x - 1, y, first))) continue;  // only where a run begins
        const a = run(x, y, first);
        const b = a >= 3 ? run(x + a, y, second) : 0;
        if (b < 3 || Math.abs(a - b) > Math.max(2, a * 0.35)) {
          x += a;
          continue;
        }
        let tall = 1;
        while (y + tall < height && at(x + Math.floor(a / 2), y + tall, first)) tall += 1;
        // A real mark is twice as wide as it is tall. Anything else is a coincidence in the picture.
        if (Math.abs((a + b) / tall - MARK.width / MARK.height) < 0.8) return { x, y, width: a + b, height: tall };
        x += a + b;
      }
    }
    return null;
  }

  const topLeft = find(isMagenta, isCyan);
  const bottomRight = find(isCyan, isMagenta);
  return topLeft && bottomRight ? { topLeft, bottomRight } : null;
}

/** The video's rectangle in picture pixels, worked out from the two marks. Null if they make no sense together. */
export function videoRect({ topLeft, bottomRight }) {
  const scale = (topLeft.width + bottomRight.width) / (2 * MARK.width);  // picture pixels per CSS pixel
  const x = topLeft.x;
  const y = topLeft.y + (MARK.height + MARK.gap) * scale;  // the mark sits `gap` above the video's top edge
  const right = bottomRight.x + bottomRight.width;
  const bottom = bottomRight.y - MARK.gap * scale;  // and the other one `gap` below its bottom edge
  const rect = { x: Math.round(x), y: Math.round(y), width: Math.round(right - x), height: Math.round(bottom - y) };
  return rect.width >= 160 && rect.height >= 90 ? rect : null;
}

// ── Small grey pictures ─────────────────────────────────────────────────────
// A grey picture is { grey, width, height }: one brightness (0-255) per pixel, row by row.

/** RGBA bytes (what canvas getImageData() returns) -> one grey value per pixel. */
export function toGrey(rgba) {
  const grey = new Uint8Array(rgba.length / 4);
  for (let i = 0, j = 0; i < grey.length; i += 1, j += 4) {
    grey[i] = (rgba[j] * 77 + rgba[j + 1] * 150 + rgba[j + 2] * 29) >> 8;  // how bright each colour looks to the eye
  }
  return grey;
}

/** The part of a grey picture inside `rect` (in its own pixels), as a grey picture of its own. */
export function cropGrey(picture, rect) {
  const grey = new Uint8Array(rect.width * rect.height);
  for (let row = 0; row < rect.height; row += 1) {
    const start = (rect.y + row) * picture.width + rect.x;
    grey.set(picture.grey.subarray(start, start + rect.width), row * rect.width);
  }
  return { grey, width: rect.width, height: rect.height };
}

// A pixel "changed" when its brightness moved by more than this. A still web page
// does not change at all from one shared picture to the next; a playing video does.
const CHANGE = 10;

/** For each pixel, 1 if it changed between two grey pictures of the same size, otherwise 0. */
export function changes(before, after) {
  const changed = new Uint8Array(after.grey.length);
  for (let i = 0; i < changed.length; i += 1) changed[i] = Math.abs(after.grey[i] - before.grey[i]) > CHANGE ? 1 : 0;
  return changed;
}

// ── Where is the video? By movement ─────────────────────────────────────────
/**
 * How often each pixel has changed lately: 0 (never) to 1 (every time).
 *
 * It is an average that forgets slowly (over about `memory` pictures), so a video
 * found once stays found through a quiet passage of play, and a video that moved
 * (the page was scrolled, the window resized) is found in its new place within seconds.
 */
export class Activity {
  constructor(width, height, { memory = 10 } = {}) {
    this.width = width;
    this.height = height;
    this.level = new Float32Array(width * height);
    this.weight = 1 / memory;
    this.samples = 0;  // how many comparisons have been added
  }

  /** Add one comparison: what changes() returned for the last two pictures. */
  add(changed) {
    const { level, weight } = this;
    for (let i = 0; i < level.length; i += 1) level[i] += (changed[i] - level[i]) * weight;
    this.samples += 1;
  }
}

/** Widen every marked pixel into a square of side 2 * radius + 1 (done as two passes, across then down). */
function widen(marked, width, height, radius) {
  const across = new Uint8Array(marked.length);
  for (let y = 0; y < height; y += 1) {
    let inWindow = 0;
    for (let x = -radius; x < width; x += 1) {
      const entering = x + radius;
      const leaving = x - radius - 1;
      if (entering < width) inWindow += marked[y * width + entering];
      if (leaving >= 0) inWindow -= marked[y * width + leaving];
      if (x >= 0) across[y * width + x] = inWindow > 0 ? 1 : 0;
    }
  }
  const down = new Uint8Array(marked.length);
  for (let x = 0; x < width; x += 1) {
    let inWindow = 0;
    for (let y = -radius; y < height; y += 1) {
      const entering = y + radius;
      const leaving = y - radius - 1;
      if (entering < height) inWindow += across[entering * width + x];
      if (leaving >= 0) inWindow -= across[leaving * width + x];
      if (y >= 0) down[y * width + x] = inWindow > 0 ? 1 : 0;
    }
  }
  return down;
}

/**
 * The moving video in a shared picture: the largest area that keeps changing.
 *
 *   activity   an Activity built from the shared pictures
 *   level      how often a pixel must change to count as moving
 *   minShare   the smallest share of the picture a video may cover
 *
 * Returns { x, y, width, height, solid } in the activity's pixels, or null when nothing moves enough.
 *
 * How: mark the pixels that keep changing, and look for the largest group of them that is
 * close to solid. That is the normal case: the camera follows the ball, so the whole picture
 * changes, and anything else moving on the page (an animated advert beside the video) is a
 * separate group. The result then has `solid: true`.
 *
 * When the camera stands still, only the players move, and the marks are scattered over the
 * grass in many small groups. A web page itself never moves, so the rectangle around all of
 * them (leaving out single specks, such as a blinking text cursor) is then the best guess,
 * with `solid: false`: an animated advert would be taken in as well. The page that uses this
 * lets a solid answer replace such a guess as soon as the camera moves.
 *
 * Either way the rectangle is one pixel in from each side, because a pixel on the very edge
 * is part video, part page.
 */
export function movingArea(activity, { level = 0.25, minShare = 0.03 } = {}) {
  const { width, height } = activity;
  const moving = new Uint8Array(width * height);
  for (let i = 0; i < moving.length; i += 1) moving[i] = activity.level[i] >= level ? 1 : 0;

  const areaOf = (box) => (box.right - box.left + 1) * (box.bottom - box.top + 1);
  const result = (box, solid) => {
    const rect = { x: box.left + 1, y: box.top + 1, width: box.right - box.left - 1, height: box.bottom - box.top - 1, solid };
    return rect.width >= 8 && rect.height >= 6 && areaOf(box) >= minShare * width * height ? rect : null;
  };

  const found = groups(moving, widen(moving, width, height, 1), width, height);
  if (!found.length) return null;
  const largest = found.reduce((best, group) => (group.count > best.count ? group : best));
  if (largest.count >= 0.5 * areaOf(largest)) {
    const solid = result(largest, true);
    if (solid) return solid;
  }
  const scattered = found.filter((group) => group.count >= 4);
  if (!scattered.length) return null;
  return result({
    left: Math.min(...scattered.map((group) => group.left)), right: Math.max(...scattered.map((group) => group.right)),
    top: Math.min(...scattered.map((group) => group.top)), bottom: Math.max(...scattered.map((group) => group.bottom)),
  }, false);
}

/**
 * The groups of touching `joined` pixels, each with how many `moving` pixels it holds and the
 * rectangle around those: [{ count, left, top, right, bottom }].
 */
function groups(moving, joined, width, height) {
  // Each group is found by filling it outwards from a starting pixel.
  const seen = new Uint8Array(width * height);
  const stack = new Int32Array(width * height);
  let size = 0;
  const visit = (i) => {
    if (joined[i] && !seen[i]) {
      seen[i] = 1;
      stack[size++] = i;
    }
  };
  const found = [];
  for (let start = 0; start < joined.length; start += 1) {
    if (!joined[start] || seen[start]) continue;
    const group = { count: 0, left: width, top: height, right: -1, bottom: -1 };
    visit(start);
    while (size) {
      const i = stack[--size];
      const x = i % width;
      const y = (i - x) / width;
      if (moving[i]) {
        group.count += 1;
        group.left = Math.min(group.left, x);
        group.right = Math.max(group.right, x);
        group.top = Math.min(group.top, y);
        group.bottom = Math.max(group.bottom, y);
      }
      if (x > 0) visit(i - 1);
      if (x < width - 1) visit(i + 1);
      if (y > 0) visit(i - width);
      if (y < height - 1) visit(i + width);
    }
    if (group.count) found.push(group);
  }
  return found;
}

/** How much two rectangles overlap: 1 when they are the same, 0 when they do not touch. */
export function overlap(a, b) {
  const across = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x);
  const down = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y);
  if (across <= 0 || down <= 0) return 0;
  const shared = across * down;
  return shared / (a.width * a.height + b.width * b.height - shared);
}

// ── Has it been paused? ─────────────────────────────────────────────────────
/**
 * What happened in the video area between two pictures of it:
 *
 *   'still'    nothing changed
 *   'local'    something changed in one place or one band only: a player's buttons
 *              fading in, a pause symbol, the mouse moving over a paused video
 *   'moving'   it changed across the picture: the match is playing
 *
 * The area is divided into a grid of `columns` x `rows` cells. A cell has changed when
 * more than 2% of its pixels changed. 'moving' needs changed cells in at least three
 * different rows AND three different columns.
 */
export function motionKind(before, after, { columns = 16, rows = 9 } = {}) {
  const { width, height } = after;
  const changed = changes(before, after);
  const cellCount = new Uint32Array(columns * rows);
  const cellSize = new Uint32Array(columns * rows);
  for (let y = 0; y < height; y += 1) {
    const row = Math.min(rows - 1, Math.floor((y * rows) / height));
    for (let x = 0; x < width; x += 1) {
      const cell = row * columns + Math.min(columns - 1, Math.floor((x * columns) / width));
      cellSize[cell] += 1;
      cellCount[cell] += changed[y * width + x];
    }
  }
  const changedRows = new Set();
  const changedColumns = new Set();
  for (let cell = 0; cell < cellCount.length; cell += 1) {
    if (cellSize[cell] && cellCount[cell] > cellSize[cell] * 0.02) {
      changedRows.add(Math.floor(cell / columns));
      changedColumns.add(cell % columns);
    }
  }
  if (!changedRows.size) return 'still';
  return changedRows.size >= 3 && changedColumns.size >= 3 ? 'moving' : 'local';
}

/**
 * Follows a video's motion from picture to picture and says when it was paused.
 *
 * Paused: three pictures in a row in which it did not move all over.
 * Playing again: three pictures in a row in which it did.
 * Requiring three keeps a pause symbol fading in, or a moment of very quiet play,
 * from flipping the answer back and forth.
 */
export class PauseWatch {
  constructor({ needed = 3 } = {}) {
    this.needed = needed;
    this.paused = false;
    this.pausedAt = null;  // the time of the first picture that stopped moving
    this.run = [];  // the latest pictures that disagree with the current answer: their times
  }

  /** Add the kind of motion seen at time `at`. Returns true when the answer changed. */
  add(kind, at) {
    const agrees = this.paused ? kind !== 'moving' : kind === 'moving';
    if (agrees) {
      this.run = [];
      return false;
    }
    this.run.push(at);
    if (this.run.length < this.needed) return false;
    this.paused = !this.paused;
    this.pausedAt = this.paused ? this.run[0] : null;
    this.run = [];
    return true;
  }

  /** Still paused, but now at another moment (it was moved while paused): the pause counts from `at`. */
  movedTo(at) {
    if (this.paused) this.pausedAt = at;
  }

  reset() {
    this.paused = false;
    this.pausedAt = null;
    this.run = [];
  }
}

// ── Which frame should be offered? ──────────────────────────────────────────
/**
 * Choose, from the frames kept lately, which ones to offer for a moment and which to pick first.
 *
 *   frames      [{ at }] oldest first; `at` is when each frame was taken (milliseconds)
 *   end         the moment itself: now, or when the video stopped moving. Later frames are left out.
 *   avoidAfter  the first pick is the latest frame taken at or before this time. Frames after it
 *               may show the player's own buttons (the pause symbol, the controls).
 *   span        how far back, in milliseconds, frames are offered
 *
 * Returns { offered: [index, ...], chosen: index } with indexes into `frames`, or null when there are none.
 */
export function chooseFrames(frames, { end, avoidAfter = end, span = 2600 }) {
  const offered = [];
  frames.forEach((frame, index) => {
    if (frame.at <= end && frame.at >= end - span) offered.push(index);
  });
  if (!offered.length) return null;
  const clean = offered.filter((index) => frames[index].at <= avoidAfter);
  return { offered, chosen: clean.length ? clean[clean.length - 1] : offered[0] };
}
