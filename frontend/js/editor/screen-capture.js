// "One-click pictures" for a video the app is not allowed to read, such as YouTube.
//
// A page cannot copy the picture out of another website's player. What a browser
// CAN do, if you say yes, is share a picture of the tab, window or screen with the
// page: the same permission a video call asks for. With that switched on, pressing
// Analyse takes one still picture, exactly as if you had taken a screenshot.
//
// FINDING THE VIDEO INSIDE WHAT WAS SHARED
// The shared picture may be the tab, the whole browser window or the whole screen,
// at any zoom. Rather than guess where the video sits in it, the page shows two
// tiny two-coloured marks just outside the video's corners while sharing is on:
//
//     [magenta|cyan]  above the top-left corner
//     [cyan|magenta]  below the bottom-right corner
//
// findMarkers() looks for those marks in the shared picture, and videoRect() works
// out the video's rectangle from them. If the marks cannot be found (another
// window was shared, or the video is scrolled out of view) nothing is captured and
// the reason is given. See .capture-mark in css/app.css for the marks themselves.

const MAX_STORED_EDGE = 1920;
// The marks' size and position in CSS pixels. Must match .capture-mark in css/app.css.
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

export function screenCaptureSupported() {
  return Boolean(navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia);
}

const wait = (milliseconds) => new Promise((resolve) => { setTimeout(resolve, milliseconds); });

/**
 * Keeps the browser's screen sharing open and takes still pictures of the video from it.
 *
 *   const grabber = new ScreenGrabber(element);   // the element that shows the marks while it has class "is-capturing"
 *   await grabber.start();                        // the browser asks you what to share
 *   const picture = await grabber.grab();         // { dataUrl, width, height } of the video area only
 */
export class ScreenGrabber {
  constructor(markedElement) {
    this.markedElement = markedElement;
    this.stream = null;
    this.video = null;
    this.onStop = () => {};
  }

  get active() {
    return Boolean(this.stream);
  }

  async start() {
    let stream;
    try {
      // The extra hints ask for "this tab" where the browser has such a choice; others ignore them.
      stream = await navigator.mediaDevices.getDisplayMedia({
        video: true, audio: false, preferCurrentTab: true, selfBrowserSurface: 'include',
      });
    } catch (error) {
      throw new Error(error && error.name === 'NotAllowedError'
        ? 'Sharing was not allowed, so nothing was shared. You can still paste a screenshot.'
        : 'This browser could not start sharing the screen. You can still paste a screenshot.');
    }
    this.stream = stream;
    this.video = document.createElement('video');
    this.video.muted = true;
    this.video.playsInline = true;
    this.video.srcObject = stream;
    stream.getVideoTracks()[0].addEventListener('ended', () => this.stop());  // you stopped sharing from the browser
    await this.video.play();
    this.markedElement.classList.add('is-capturing');
  }

  stop() {
    if (!this.stream) return;
    this.stream.getTracks().forEach((track) => track.stop());
    this.stream = null;
    this.video = null;
    this.markedElement.classList.remove('is-capturing');
    this.onStop();
  }

  /** One still picture of the video area. Throws an Error whose message can be shown as it is. */
  async grab() {
    if (!this.stream) throw new Error('One-click pictures are not switched on.');
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('2d', { willReadFrequently: true });
    // The marks may have appeared a moment ago, and the shared picture arrives a
    // little late, so look a few times before deciding they are not there.
    for (let attempt = 0; attempt < 5; attempt += 1) {
      const width = this.video.videoWidth;
      const height = this.video.videoHeight;
      if (width && height) {
        canvas.width = width;
        canvas.height = height;
        context.drawImage(this.video, 0, 0, width, height);
        const marks = findMarkers(context.getImageData(0, 0, width, height).data, width, height);
        const rect = marks && videoRect(marks);
        if (rect) {
          const scale = Math.min(1, MAX_STORED_EDGE / Math.max(rect.width, rect.height));
          const still = document.createElement('canvas');
          still.width = Math.round(rect.width * scale);
          still.height = Math.round(rect.height * scale);
          still.getContext('2d').drawImage(canvas, rect.x, rect.y, rect.width, rect.height, 0, 0, still.width, still.height);
          return { dataUrl: still.toDataURL('image/jpeg', 0.9), width: still.width, height: still.height };
        }
      }
      await wait(250);
    }
    throw new Error('The video could not be found in what is being shared. Share this browser window (or the screen it '
      + 'is on), and keep the whole video in view.');
  }
}
