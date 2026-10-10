// A drawing surface: one SVG that shows one layer of a diagram.
//
// There are two kinds, and the only difference between them is the coordinate
// system (the `space`) they are given:
//
//   new Surface({ space: new FrameSpace(1280, 720), ... })   draws over a video frame
//   new Surface({ space: new PitchSpace(105, 68), ... })     draws on the pitch
//
// A surface is deliberately simple. It draws what it is told to draw, and it
// turns a mouse or touch event into a point in STORED coordinates. Deciding what
// a click means is the controller's job (controller.js).
//
// WHY THE DRAWING ALWAYS LINES UP WITH THE PICTURE
// The wrapper <div> is given the exact shape of the view (CSS aspect-ratio), the
// SVG fills it, and the picture is drawn INSIDE the same SVG in the same view
// units. Picture and shapes are therefore scaled together by the browser. Nothing
// is positioned in screen pixels, so there is nothing to go out of step on resize.

import { h, svg } from '../dom.js';
import { clientToView } from './coords.js';
import { drawHandles, drawShape } from './render.js';

export class Surface {
  /**
   * @param space        a FrameSpace or PitchSpace (coords.js)
   * @param label        what the surface is, for screen readers
   * @param interactive  false for a read-only diagram (profile pages, exports)
   */
  constructor({ space, label, interactive = true }) {
    this.space = space;
    this.layer = space.layer;
    this.interactive = interactive;

    this.background = svg('g', { 'data-part': 'background' });
    this.shapes = svg('g', { 'data-part': 'shapes' });
    this.overlay = svg('g', { 'data-part': 'overlay' });  // selection handles and the shape being drawn

    const { x, y, width, height } = space.view;
    this.svg = svg('svg', {
      viewBox: `${x} ${y} ${width} ${height}`,
      preserveAspectRatio: 'xMidYMid meet',  // scale to fit, centred, never stretched
      role: interactive ? 'application' : 'img',
      'aria-label': label,
      tabindex: interactive ? 0 : null,
    }, this.background, this.shapes, this.overlay);

    this.element = h('div', { class: interactive ? 'surface editing' : 'surface is-readonly' }, this.svg);
    this.element.style.aspectRatio = `${width} / ${height}`;
  }

  /** Put something behind the shapes: the pitch markings, or a frame picture. */
  setBackground(...nodes) {
    this.background.replaceChildren(...nodes);
  }

  /** Show a picture (a captured frame or a screenshot) filling the whole view. */
  setPicture(url) {
    const { width, height } = this.space.view;
    this.setBackground(svg('image', { href: url, x: 0, y: 0, width, height, preserveAspectRatio: 'none' }));
  }

  /** Where a mouse/touch event happened, as a tidy point in STORED coordinates. */
  pointFromEvent(event) {
    const view = clientToView([event.clientX, event.clientY], this.svg.getBoundingClientRect(), this.space.view);
    return this.space.tidy(this.space.fromView(view));
  }

  /** Which shape (and which of its handles) an event landed on, or null for empty space. */
  hitFromEvent(event) {
    if (!(event.target instanceof Element)) return null;
    const handle = event.target.closest('[data-handle]');
    if (handle) return { uid: handle.dataset.uid, handle: Number(handle.dataset.handle) };
    const shape = event.target.closest('[data-uid]');
    return shape ? { uid: shape.dataset.uid, handle: null } : null;
  }

  /**
   * Redraw everything. Cheap enough to do on every change: a diagram has dozens
   * of shapes, not thousands.
   *
   * @param shapes       the shapes of this surface's layer, in drawing order
   * @param selectedUid  the selected shape, which gets handles
   * @param draft        a half-drawn shape to preview, or null
   */
  draw(shapes, { selectedUid = null, draft = null } = {}) {
    // Redrawing replaces the elements. If a shape had keyboard focus, give focus
    // to its replacement so arrow keys keep working.
    const focused = this.shapes.contains(document.activeElement)
      ? document.activeElement.closest('[data-uid]')?.dataset.uid
      : null;

    this.shapes.replaceChildren(...shapes.map((shape) => drawShape(shape, this.space, { interactive: this.interactive })));

    const overlay = [];
    if (draft) {
      const preview = drawShape(draft, this.space);
      preview.setAttribute('opacity', '0.7');
      preview.setAttribute('pointer-events', 'none');
      overlay.push(preview);
    }
    const selected = shapes.find((shape) => shape.uid === selectedUid);
    if (selected && this.interactive) overlay.push(...drawHandles(selected, this.space));
    this.overlay.replaceChildren(...overlay);

    if (focused) {
      const replacement = [...this.shapes.children].find((node) => node.dataset.uid === focused);
      if (replacement) replacement.focus({ preventScroll: true });
      else this.svg.focus({ preventScroll: true });
    }
  }
}
