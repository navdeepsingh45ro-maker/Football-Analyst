// Sharing the screen with the page, and keeping the last seconds of the video from it.
//
// A page cannot copy the picture out of another website's player, or out of another
// window. What a browser CAN do, if you say yes, is share a moving picture of a
// window or of the whole screen with the page: the same permission a video call
// asks for. The app uses it in two ways:
//
//   OwnPlayerPictures   "one-click pictures" for the YouTube player inside the app.
//                       The video is found by two small marks beside its corners.
//   MatchWindow         a match playing in another window: any website, or a video
//                       app such as QuickTime. The video is found by its movement.
//
// Both keep the frames of the last couple of seconds (FrameRing). That is what lets
// Analyse, pressed after you paused, still offer the frame from just BEFORE the
// pause, when the player had not yet covered the picture with its buttons.
//
// Nothing is recorded or sent anywhere. The frames are held in memory for a few
// seconds and then replaced; only the one you save is stored. Finding the video
// and telling a pause are done by the pure functions in find-video.js.

import {
  Activity, PauseWatch, changes, chooseFrames, cropGrey, findMarkers, motionKind, movingArea, overlap, toGrey, videoRect,
} from './find-video.js';

const SAMPLE_EVERY = 200;   // milliseconds between looks at the shared picture: five a second
const KEEP_FRAMES = 14;     // how many recent frames are kept: just under three seconds
const FRAME_EDGE = 1600;    // the longer side of a kept frame, in pixels, at most
// After a pause, the player's own buttons may already be in the frames of the last moment
// before the picture went still (they fade in). The first frame offered is this much earlier.
const SETTLE = 600;

export function screenSharingSupported() {
  return Boolean(navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia);
}

const wait = (milliseconds) => new Promise((resolve) => { setTimeout(resolve, milliseconds); });

/** The browser's screen sharing: the moving picture, and copies taken from it. */
class ScreenShare {
  constructor(onStop) {
    this.stream = null;
    this.video = null;   // a <video> that is never shown: it only receives the shared picture
    this.timer = null;
    this.small = null;   // the canvas for small grey copies, reused
    this.onStop = onStop;
  }

  get active() { return Boolean(this.stream); }

  get width() { return this.video ? this.video.videoWidth : 0; }

  get height() { return this.video ? this.video.videoHeight : 0; }

  /** Ask the browser to share. `options` may carry hints that only some browsers understand; the others ignore them. */
  async start(options) {
    let stream;
    try {
      stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false, ...options });
    } catch (error) {
      throw new Error(error && error.name === 'NotAllowedError'
        ? 'Sharing was not allowed, so nothing was shared.'
        : 'This browser could not start sharing the screen.');
    }
    this.stream = stream;
    this.video = document.createElement('video');
    this.video.muted = true;
    this.video.playsInline = true;
    this.video.srcObject = stream;
    stream.getVideoTracks()[0].addEventListener('ended', () => this.stop());  // you stopped sharing from the browser
    await this.video.play();
  }

  /** Call `look` every `milliseconds` while the shared picture has a size. */
  every(milliseconds, look) {
    clearInterval(this.timer);
    this.timer = setInterval(() => { if (this.width && this.height) look(); }, milliseconds);
  }

  stop() {
    if (!this.stream) return;
    clearInterval(this.timer);
    this.stream.getTracks().forEach((track) => track.stop());
    this.stream = null;
    this.video = null;
    this.onStop();
  }

  /** The whole shared picture as it is now, at full size, on a canvas. */
  whole() {
    const canvas = document.createElement('canvas');
    canvas.width = this.width;
    canvas.height = this.height;
    canvas.getContext('2d').drawImage(this.video, 0, 0);
    return canvas;
  }

  /** A small grey copy of the whole shared picture, `width` pixels across (see find-video.js). */
  grey(width) {
    const height = Math.max(1, Math.round((width * this.height) / this.width));
    if (!this.small || this.small.width !== width || this.small.height !== height) {
      this.small = document.createElement('canvas');
      this.small.width = width;
      this.small.height = height;
    }
    const context = this.small.getContext('2d', { willReadFrequently: true });
    context.drawImage(this.video, 0, 0, width, height);
    return { grey: toGrey(context.getImageData(0, 0, width, height).data), width, height };
  }
}

/** The frames of the last few seconds: copies of the video area, oldest first. Canvases are reused. */
class FrameRing {
  constructor(limit = KEEP_FRAMES) {
    this.limit = limit;
    this.frames = [];  // [{ canvas, width, height, at, time }]
    this.spare = [];
  }

  /**
   * Keep a copy of `area` (in shared-picture pixels) of what `video` shows, taken at time `at`.
   * `time` is the match video's own position then, where the app knows it, otherwise null.
   */
  push(video, area, at, time = null) {
    const scale = Math.min(1, FRAME_EDGE / Math.max(area.width, area.height));
    const width = Math.round(area.width * scale);
    const height = Math.round(area.height * scale);
    const canvas = this.frames.length >= this.limit ? this.frames.shift().canvas : (this.spare.pop() || document.createElement('canvas'));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    canvas.getContext('2d').drawImage(video, area.x, area.y, area.width, area.height, 0, 0, width, height);
    this.frames.push({ canvas, width, height, at, time });
  }

  /** Forget the frames taken after `at`: for example the identical copies of a paused picture. */
  dropAfter(at) {
    while (this.frames.length && this.frames[this.frames.length - 1].at > at) this.spare.push(this.frames.pop().canvas);
  }

  clear() {
    this.spare.push(...this.frames.map((frame) => frame.canvas));
    this.frames = [];
  }
}

function toJpeg(canvas, quality = 0.9) {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('The picture could not be made.'))), 'image/jpeg', quality);
  });
}

/** A small copy for the row of frames to choose from. */
function thumbnail(canvas, width = 200) {
  const small = document.createElement('canvas');
  small.width = width;
  small.height = Math.max(1, Math.round((canvas.height * width) / canvas.width));
  small.getContext('2d').drawImage(canvas, 0, 0, small.width, small.height);
  return toJpeg(small, 0.8);
}

/**
 * The frames to offer for a moment, as pictures the page can show and save.
 * Resolves to { pictures: [{ blob, url, thumb, width, height, before }], chosen } where `before`
 * is how many seconds before the moment (`end`) the picture was taken. The page must call
 * URL.revokeObjectURL() on `url` and `thumb` when it no longer needs them.
 */
async function offer(frames, choice, end) {
  if (!choice) return null;
  const pictures = await Promise.all(choice.offered.map(async (index) => {
    const frame = frames[index];
    const [blob, small] = await Promise.all([toJpeg(frame.canvas), thumbnail(frame.canvas)]);
    return {
      blob, url: URL.createObjectURL(blob), thumb: URL.createObjectURL(small),
      width: frame.width, height: frame.height, before: (end - frame.at) / 1000,
    };
  }));
  return { pictures, chosen: choice.offered.indexOf(choice.chosen) };
}

// ── One-click pictures, for the YouTube player inside the app ───────────────
/**
 * Keeps sharing this browser window (or the screen it is on) and copies the area of the
 * app's own YouTube player from it, a few times a second, while the video plays.
 *
 *   const pictures = new OwnPlayerPictures(element, { isPlaying: () => tube.playing, timeNow: () => tube.time });
 *   await pictures.start();          // the browser asks what to share
 *   await pictures.moment({ ... });  // the frames to offer when you press Analyse
 *
 * WHERE THE PLAYER IS IN THE SHARED PICTURE
 * While this is on, `element` (the box around the player) shows the two marks of
 * find-video.js beside its corners. Finding them once tells how the page lies inside
 * the shared picture: how many shared pixels there are per CSS pixel, and where the
 * page starts. After that the player's place on the page (getBoundingClientRect) gives
 * its place in the picture, even after you scroll. When the window is resized, moved or
 * zoomed, the marks are looked for again.
 */
export class OwnPlayerPictures {
  constructor(element, { isPlaying, timeNow = () => null, onStop = () => {} }) {
    this.element = element;
    this.isPlaying = isPlaying;
    this.timeNow = timeNow;
    this.share = new ScreenShare(() => {
      this.element.classList.remove('is-capturing');
      this.ring.clear();
      this.fit = null;
      onStop();
    });
    this.ring = new FrameRing();
    this.fit = null;  // { scale, x, y, layout }: how the page lies in the shared picture
    this.fitting = false;
  }

  get active() { return this.share.active; }

  async start() {
    // The hints ask for "this tab" where the browser offers such a choice.
    await this.share.start({ preferCurrentTab: true, selfBrowserSurface: 'include', surfaceSwitching: 'exclude' });
    this.element.classList.add('is-capturing');
    if (!await this.#findPage()) {
      this.stop();
      throw new Error('The video could not be found in what is being shared. Share this browser window (or the screen '
        + 'it is on), and keep the whole video in view.');
    }
    this.share.every(SAMPLE_EVERY, () => this.#look());
  }

  stop() { this.share.stop(); }

  /** Everything that, when it changes, moves the page inside the shared picture. */
  static #layout() {
    return [window.innerWidth, window.innerHeight, window.screenX, window.screenY, window.devicePixelRatio].join(' ');
  }

  /** Find the marks and work out how the page lies in the shared picture. Tries a few times. */
  async #findPage() {
    this.fitting = true;
    try {
      // The marks may have appeared a moment ago, and the shared picture arrives a little late.
      for (let attempt = 0; attempt < 6 && this.share.active; attempt += 1) {
        if (this.share.width && this.share.height) {
          const canvas = this.share.whole();
          const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
          const marks = findMarkers(pixels, canvas.width, canvas.height);
          const rect = marks && videoRect(marks);
          const box = this.element.getBoundingClientRect();
          if (rect && box.width) {
            const scale = rect.width / box.width;
            this.fit = { scale, x: rect.x - box.left * scale, y: rect.y - box.top * scale, layout: OwnPlayerPictures.#layout() };
            return true;
          }
        }
        await wait(250);
      }
      return false;
    } finally {
      this.fitting = false;
    }
  }

  /** Where the player is in the shared picture now, or null when it is not all in view. */
  #area() {
    if (!this.fit) return null;
    const box = this.element.getBoundingClientRect();
    if (box.left < 0 || box.top < 0 || box.right > window.innerWidth || box.bottom > window.innerHeight) return null;
    const { scale, x, y } = this.fit;
    const area = {
      x: Math.round(x + box.left * scale), y: Math.round(y + box.top * scale),
      width: Math.round(box.width * scale), height: Math.round(box.height * scale),
    };
    const inside = area.x >= 0 && area.y >= 0 && area.x + area.width <= this.share.width && area.y + area.height <= this.share.height;
    return inside && area.width > 0 && area.height > 0 ? area : null;
  }

  #look() {
    if (this.fitting) return;
    if (this.fit && this.fit.layout !== OwnPlayerPictures.#layout()) {
      this.fit = null;
      this.ring.clear();  // taken with the old layout: they may not show the player any more
      this.#findPage();
      return;
    }
    if (!this.isPlaying()) return;  // keep the frames from before a pause
    const area = this.#area();
    if (area) this.ring.push(this.share.video, area, performance.now(), this.timeNow());
  }

  /**
   * The frames to offer when you press Analyse (see offer() above).
   *   pausedAt   when the player was paused with its own button (performance.now() time),
   *              or null when it is playing: then a fresh frame is taken first, and chosen
   *   enteredAt  when the mouse last went over the player. When you paused with the player's
   *              own button, its controls showed from then on, so a frame from before is chosen.
   *   time       where the paused player is now. When it was moved while paused (you went back
   *              to look again), the frames kept from before the pause show another moment, so a
   *              fresh picture is taken of what it shows now instead.
   * Throws an Error whose message can be shown as it is.
   */
  async moment({ pausedAt = null, enteredAt = null, time = null } = {}) {
    if (!this.fit) {
      if (!await this.#findPage()) throw new Error('The video could not be found in what is being shared. Keep the whole video in view.');
    }
    const last = this.ring.frames[this.ring.frames.length - 1];
    const moved = pausedAt !== null && (!last || last.time === null || time === null || Math.abs(time - last.time) > 0.7);
    let end = pausedAt;
    let avoidAfter;
    if (pausedAt === null || moved) {
      const area = this.#area();
      if (!area) throw new Error('Scroll so that the whole video is in view, then press Analyse again.');
      end = performance.now();
      if (moved) this.ring.clear();
      this.ring.push(this.share.video, area, end, time);
      avoidAfter = end;
    } else {
      // The pause symbol appears at once; the message saying so arrives a little after it.
      avoidAfter = pausedAt - 150;
      if (enteredAt !== null && enteredAt <= pausedAt && enteredAt > pausedAt - 4000) avoidAfter = Math.min(avoidAfter, enteredAt);
    }
    const choice = chooseFrames(this.ring.frames, { end, avoidAfter });
    if (!choice) throw new Error('No picture of the video was kept yet. Play it for a moment, then press Analyse again.');
    return offer(this.ring.frames, choice, end);
  }
}

// ── A match playing in another window ───────────────────────────────────────
/**
 * Shares the window (or screen) where a match is playing, finds the video in it by its
 * movement, follows it if it moves, tells when it is paused, and keeps the last frames.
 *
 *   const match = new MatchWindow({ onChange: (what) => ... });
 *   await match.start();        // the browser asks what to share
 *   match.state                 // 'looking' | 'found' | 'not-found'
 *   match.paused                // true when the video has stood still for a moment
 *   await match.moment();       // the frames to offer when you press Analyse
 *
 * `onChange` is told 'looking', 'found', 'moved', 'not-found', 'paused', 'playing' or 'stopped'.
 */
export class MatchWindow {
  constructor({ onChange = () => {} } = {}) {
    this.onChange = onChange;
    this.share = new ScreenShare(() => {
      this.ring.clear();
      this.onChange('stopped');
    });
    this.ring = new FrameRing();
    this.pause = new PauseWatch();
    this.area = null;     // the video, in shared-picture pixels: { x, y, width, height }
    this.solid = false;   // was the area found while the whole picture moved (see movingArea)
    this.manual = false;  // marked by hand: then it is not looked for automatically
    this.size = null;     // the shared picture's size, once it has been seen
    this.columns = 0;     // the width of the grey copies made of it
    this.#restart();
  }

  get active() { return this.share.active; }

  get paused() { return this.pause.paused; }

  get state() {
    if (this.area) return 'found';
    return this.lookingSince !== null && performance.now() - this.lookingSince > 9000 ? 'not-found' : 'looking';
  }

  async start() {
    // The hints ask to leave this app's own tab out of the choice, where the browser offers tabs.
    await this.share.start({ selfBrowserSurface: 'exclude', surfaceSwitching: 'include', monitorTypeSurfaces: 'include' });
    this.share.every(SAMPLE_EVERY, () => this.#look());
    this.onChange('looking');
  }

  stop() { this.share.stop(); }

  /** Forget where the video was and look for it from the beginning. */
  #restart() {
    this.activity = null;
    this.before = null;     // the previous grey copy of the whole picture
    this.beforePart = null; // the previous grey copy of the video area
    this.pausedPart = null; // the grey copy of the video area when it was paused
    this.proposal = null;   // an area seen once, waiting to be seen again before it is used
    this.looks = 0;
    this.lookingSince = performance.now();
    if (!this.manual) this.area = null;
    this.ring.clear();
    this.pause.reset();
  }

  /** Use this area of the shared picture as the video (marked by hand). */
  setArea(area) {
    this.manual = true;
    this.area = area;
    this.solid = true;
    this.beforePart = null;
    this.ring.clear();
    this.pause.reset();
    this.onChange('found');
  }

  /** Look for the video automatically again, after it was marked by hand. */
  findAgain() {
    this.manual = false;
    this.#restart();
    this.onChange('looking');
  }

  /** The whole shared picture as it is now (for marking the video by hand). */
  whole() { return this.share.whole(); }

  /** Draw what the app watches into `canvas`: the video once it is found, otherwise the whole shared picture. */
  preview(canvas) {
    if (!this.share.active || !this.share.width) return;
    const source = this.area || { x: 0, y: 0, width: this.share.width, height: this.share.height };
    const height = Math.max(1, Math.round((canvas.width * source.height) / source.width));
    if (canvas.height !== height) canvas.height = height;
    canvas.getContext('2d').drawImage(this.share.video, source.x, source.y, source.width, source.height, 0, 0, canvas.width, height);
  }

  /** The area as a rectangle in the grey copies. */
  #inGrey(area) {
    const scale = this.columns / this.share.width;
    const x = Math.floor(area.x * scale);
    const y = Math.floor(area.y * scale);
    return {
      x, y,
      width: Math.max(1, Math.min(this.columns - x, Math.floor(area.width * scale))),
      height: Math.max(1, Math.min(this.activity.height - y, Math.floor(area.height * scale))),
    };
  }

  #look() {
    const now = performance.now();
    const size = `${this.share.width}x${this.share.height}`;
    if (size !== this.size) {
      if (this.size !== null) {
        // A new size of shared picture (the window was resized): everything is somewhere else,
        // including an area marked by hand.
        const hadArea = Boolean(this.area);
        this.manual = false;
        this.#restart();
        if (hadArea) this.onChange('looking');
      }
      this.size = size;
      this.columns = Math.max(240, Math.min(400, Math.round(this.share.width / 5)));
      this.activity = null;
      this.before = null;
      this.beforePart = null;
    }
    const picture = this.share.grey(this.columns);
    if (!this.activity) this.activity = new Activity(picture.width, picture.height);
    if (this.before) this.activity.add(changes(this.before, picture));
    this.before = picture;
    this.looks += 1;

    if (!this.manual && this.activity.samples >= 8 && this.looks % 5 === 0) this.#placeVideo();
    if (!this.area) {
      if (this.state === 'not-found' && this.looks % 5 === 0) this.onChange('not-found');
      return;
    }

    const part = cropGrey(picture, this.#inGrey(this.area));
    if (this.beforePart && this.beforePart.grey.length === part.grey.length) {
      const kind = motionKind(this.beforePart, part);
      if (this.pause.add(kind, now)) {
        if (this.pause.paused) {
          this.ring.dropAfter(this.pause.pausedAt);  // keep one copy of the paused picture
          this.pausedPart = part;
        }
        this.onChange(this.pause.paused ? 'paused' : 'playing');
      } else if (this.pause.paused && kind === 'still' && motionKind(this.pausedPart, part) === 'moving') {
        // Still paused, but at another moment: it was moved while paused, to look again. The frames
        // from before the pause show something else now, so this picture becomes the paused one.
        this.ring.clear();
        this.ring.push(this.share.video, this.area, now);
        this.pause.movedTo(now);
        this.pausedPart = part;
      }
    }
    this.beforePart = part;
    if (!this.pause.paused) this.ring.push(this.share.video, this.area, now);
  }

  /** Look at where things move; use a new place for the video once it has been seen twice in a row. */
  #placeVideo() {
    const found = movingArea(this.activity);
    if (!found) {
      this.proposal = null;
      return;
    }
    const scale = this.share.width / this.columns;
    const area = {
      x: Math.round(found.x * scale), y: Math.round(found.y * scale),
      width: Math.round(found.width * scale), height: Math.round(found.height * scale),
    };
    const seenBefore = this.proposal && overlap(area, this.proposal) > 0.9;
    this.proposal = area;
    if (!seenBefore) return;

    // Moved elsewhere: only to something solid and about as big. While the match is paused, an
    // animated advert on the same page is what moves, and must not be taken for the match.
    const size = (rect) => rect.width * rect.height;
    const wanted = !this.area
      || (found.solid && !this.solid)  // a sure answer replaces a guess
      || (overlap(area, this.area) < 0.8 && found.solid && size(area) >= 0.5 * size(this.area));
    if (!wanted) return;
    const first = !this.area;
    this.area = area;
    this.solid = found.solid;
    this.beforePart = null;
    this.ring.clear();
    this.pause.reset();
    this.onChange(first ? 'found' : 'moved');
  }

  /** The frames to offer when you press Analyse (see offer() above), or null when there are none yet. */
  async moment() {
    const frames = this.ring.frames;
    if (!this.area || !frames.length) return null;
    const choice = this.pause.paused
      ? chooseFrames(frames, { end: this.pause.pausedAt, avoidAfter: this.pause.pausedAt - SETTLE })
      : chooseFrames(frames, { end: frames[frames.length - 1].at });
    return offer(frames, choice, this.pause.paused ? this.pause.pausedAt : frames[frames.length - 1].at);
  }
}
