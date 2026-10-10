// Getting a still picture to draw on: from the paused video, or from a file you supply.
//
// WHAT THE BROWSER ALLOWS
// A page may copy the pixels of a <video> only if the video comes from the same
// address as the page, or from a site that explicitly permits it (CORS). For a
// local match file that is always the case, because this app streams the file
// itself. For a video hosted elsewhere it usually is not, and the browser then
// throws a SecurityError. That is a deliberate privacy protection in every
// browser, not a bug in this app, and this file never tries to get around it.
// captureVideoFrame() reports it clearly so the page can offer what IS allowed:
// a screenshot you take yourself (frameFromImageFile()), or a still the browser
// shares with the page after asking you (see screen-capture.js).

/** The longest side, in pixels, of a picture the app stores. Larger frames are scaled down. */
const MAX_STORED_EDGE = 1920;

export class FrameCaptureError extends Error {
  constructor(reason, message) {
    super(message);
    this.reason = reason;  // 'not-ready' | 'blocked'
  }
}

function drawScaled(source, width, height) {
  const scale = Math.min(1, MAX_STORED_EDGE / Math.max(width, height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  canvas.getContext('2d').drawImage(source, 0, 0, canvas.width, canvas.height);
  return canvas;
}

/**
 * Copy the picture currently shown by a paused <video>.
 *
 * Returns { dataUrl, width, height }. width and height are the ORIGINAL frame
 * size of the video (video.videoWidth / videoHeight). Drawings are stored as
 * fractions of the frame, so they stay correct even though the stored picture
 * itself may be scaled down to save space.
 */
export function captureVideoFrame(video) {
  const width = video.videoWidth;
  const height = video.videoHeight;
  if (!width || !height) {
    throw new FrameCaptureError('not-ready',
      'The video has not shown a picture yet. Let it play for a moment, pause, and try again.');
  }
  const canvas = drawScaled(video, width, height);
  try {
    return { dataUrl: canvas.toDataURL('image/jpeg', 0.9), width, height };
  } catch {
    throw new FrameCaptureError('blocked',
      'The browser does not allow copying a picture out of this video, because it is hosted on another website '
      + 'that has not permitted it. Take a screenshot of the moment and add it here instead.');
  }
}

/**
 * Turn a picture you supply (chosen, dropped or pasted) into a frame to draw on.
 * Returns { dataUrl, width, height } with the picture's own size.
 */
export async function frameFromImageFile(file) {
  if (!file || !file.type.startsWith('image/')) {
    throw new Error('That is not a picture. Use a PNG or JPEG screenshot.');
  }
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = () => reject(new Error('The picture could not be read.'));
      image.src = url;
    });
    const canvas = drawScaled(image, image.naturalWidth, image.naturalHeight);
    // Stored at the size it was scaled to, so its recorded size matches the stored picture.
    return { dataUrl: canvas.toDataURL('image/jpeg', 0.9), width: canvas.width, height: canvas.height };
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** The first picture in a paste or drop event, or null. */
export function imageFromTransfer(dataTransfer) {
  if (!dataTransfer) return null;
  for (const item of dataTransfer.items || []) {
    if (item.kind === 'file' && item.type.startsWith('image/')) return item.getAsFile();
  }
  return [...(dataTransfer.files || [])].find((file) => file.type.startsWith('image/')) || null;
}
