// Saving a diagram as a PNG picture, and downloading files in general.
//
// HOW A DIAGRAM BECOMES A PICTURE
// A diagram is an SVG. The browser can draw an SVG into a <canvas>, and a canvas
// can be saved as a PNG. Three details make that work:
//   1. The copy must be self-contained, so the frame picture is embedded in it
//      (an SVG loaded as an image may not fetch anything else).
//   2. Editing aids (selection handles, invisible click areas) are left out.
//   3. Shapes are styled with SVG attributes, not page CSS (see render.js), since
//      the page's stylesheet does not apply inside the copy.

import { h } from '../dom.js';

async function asDataUrl(url) {
  const blob = await (await fetch(url)).blob();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('The frame picture could not be read.'));
    reader.readAsDataURL(blob);
  });
}

/**
 * Render a Surface (surface.js) to a PNG Blob.
 * A frame is exported at its own pixel size; the pitch at 1600 pixels wide.
 */
export async function surfaceToPng(surface) {
  const copy = surface.svg.cloneNode(true);
  copy.querySelectorAll('[data-export="skip"], [data-part="overlay"]').forEach((node) => node.remove());
  copy.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  for (const image of copy.querySelectorAll('image')) {
    const href = image.getAttribute('href');
    if (href && !href.startsWith('data:')) image.setAttribute('href', await asDataUrl(href));
  }

  const view = surface.space.view;
  const width = surface.layer === 'frame' ? Math.min(view.width, 1920) : 1600;
  const height = Math.round((width * view.height) / view.width);
  copy.setAttribute('width', width);
  copy.setAttribute('height', height);

  const source = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(copy)], { type: 'image/svg+xml' }));
  try {
    const image = new Image();
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = () => reject(new Error('The diagram could not be turned into a picture.'));
      image.src = source;
    });
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    canvas.getContext('2d').drawImage(image, 0, 0, width, height);
    return await new Promise((resolve, reject) => {
      canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('The picture could not be created.'))), 'image/png');
    });
  } finally {
    URL.revokeObjectURL(source);
  }
}

/** Offer a Blob (or text) to the user as a file download. */
export function downloadFile(content, fileName, type = 'application/octet-stream') {
  const blob = content instanceof Blob ? content : new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = h('a', { href: url, download: fileName });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** A safe file name from free text: "Run behind the CB!" -> "run-behind-the-cb". */
export function slug(text, fallback = 'diagram') {
  const cleaned = String(text || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60);
  return cleaned || fallback;
}
