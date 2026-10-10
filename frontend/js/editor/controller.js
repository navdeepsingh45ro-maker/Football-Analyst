// The editor's behaviour: what a click, a drag or a key press DOES.
//
//   model.js       holds the shapes           (data)
//   surface.js     draws them, reports clicks (view)
//   controller.js  decides what happens       (this file)
//
// THE RULES
//   Select tool      press a shape to select it; drag to move it; drag a square
//                    handle to move one point; press empty space to deselect.
//   Marker tools     each click places one marker. The tool stays active so a
//                    whole back line can be placed quickly. Esc to stop.
//   Two-point tools  (run, pass, line, space): press at the start, drag, release
//                    at the end. Or click once for the start and once for the end.
//   Angle tool       three clicks: first end, the corner, the other end.
//   After drawing a line, space, angle or text, the Select tool comes back with
//   the new shape selected, ready to be labelled.
//
//   Keyboard (when a surface has focus)
//     Tab             step through the shapes        Enter / Space   select the focused shape,
//     Arrow keys      nudge the selection                            or place the current tool's
//     Shift + arrows  nudge five times as far                        shape in the middle
//     Delete          remove the selection           Esc             cancel / back to Select
//   Together with the number boxes in the Selected shape panel, everything that
//   can be done by dragging can also be done without a mouse.

import { KINDS } from './model.js';

const HINTS = {
  select: 'Press a shape to select it, drag to move it. Arrow keys nudge, Delete removes, Tab steps through shapes.',
  marker: (name) => `Click to place: ${name}. The tool stays on so you can place several. Press Esc when done.`,
  movement: 'Press where the run starts, drag to where it ends, release. (Or click the start, then the end.)',
  pass: 'Press where the pass starts, drag to where it goes, release. (Or click twice.)',
  line: 'Press at one end, drag to the other, release. (Or click twice.)',
  zone: 'Press at one corner of the space, drag to the opposite corner, release. (Or click both corners.)',
  angle: 'Click three points: one end, then the corner, then the other end.',
  text: 'Click where the text should go, then type it in the Selected shape panel.',
};

export class EditorController {
  /**
   * @param doc          the AnnotationDocument being edited
   * @param surfaces     the Surface(s) showing it (frame, pitch, or both)
   * @param defaultsFor  optional (kind, layer) => extra fields for a new shape,
   *                     e.g. to link the studied-player marker to the chosen player
   */
  constructor(doc, surfaces, { defaultsFor } = {}) {
    this.doc = doc;
    this.surfaces = surfaces;
    this.defaultsFor = defaultsFor || (() => ({}));
    this.tool = 'select';
    this.selectedUid = null;
    this.justCreatedUid = null;  // lets the panel put the cursor in a new shape's label box
    this.draft = null;           // a shape being drawn: { surface, kind, points, cursor, pressedAt }
    this.drag = null;            // a move in progress: { surface, uid, handle, last }
    this.listeners = new Set();

    doc.onChange(() => {
      if (this.selectedUid && !doc.find(this.selectedUid)) this.selectedUid = null;
      this.refresh();
    });
    for (const surface of surfaces) this.#listenTo(surface);
    this.refresh();
  }

  /** Be told whenever the tool, selection or diagram changes (the panels use this). */
  onState(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  get selected() { return this.selectedUid ? this.doc.find(this.selectedUid) : null; }

  get hint() {
    if (this.tool === 'select') return HINTS.select;
    return KINDS[this.tool].marker ? HINTS.marker(KINDS[this.tool].label.toLowerCase()) : HINTS[this.tool];
  }

  surfaceFor(layer) { return this.surfaces.find((surface) => surface.layer === layer) || null; }

  /** Redraw every surface and tell the panels. */
  refresh() {
    for (const surface of this.surfaces) {
      surface.draw(this.doc.onLayer(surface.layer), {
        selectedUid: this.selectedUid,
        draft: this.draft && this.draft.surface === surface ? this.#draftShape() : null,
      });
      surface.element.classList.toggle('tool-select', this.tool === 'select');
    }
    for (const listener of this.listeners) listener();
  }

  setTool(tool) {
    this.tool = tool;
    this.draft = null;
    if (tool !== 'select') this.selectedUid = null;
    this.refresh();
  }

  select(uid) {
    this.selectedUid = uid;
    this.refresh();
  }

  deleteSelected() {
    if (this.selectedUid) this.doc.remove(this.selectedUid);
  }

  /** Place the current tool's shape in the middle of a surface (the keyboard way to draw). */
  placeAtCentre(surface) {
    if (this.tool === 'select') return;
    const { x, y, width, height } = surface.space.view;
    const centre = [x + width / 2, y + height / 2];
    const u = surface.space.unit;
    const offsets = {
      1: [[0, 0]],
      2: this.tool === 'zone' ? [[-6 * u, -4 * u], [6 * u, 4 * u]] : [[-6 * u, 0], [6 * u, 0]],
      3: [[7 * u, 0], [0, 0], [5 * u, -5 * u]],
    }[KINDS[this.tool].points];
    const points = offsets.map(([dx, dy]) => surface.space.tidy(surface.space.fromView([centre[0] + dx, centre[1] + dy])));
    this.draft = { surface, kind: this.tool, points };
    this.#finishDraft();
  }

  // ── Pointer (mouse, touch, pen) ────────────────────────────────────────────
  #listenTo(surface) {
    if (!surface.interactive) return;
    surface.svg.addEventListener('pointerdown', (event) => this.#pointerDown(surface, event));
    surface.svg.addEventListener('pointermove', (event) => this.#pointerMove(surface, event));
    surface.svg.addEventListener('pointerup', (event) => this.#pointerUp(surface, event));
    surface.svg.addEventListener('pointercancel', () => this.#cancelPointer());
    surface.svg.addEventListener('keydown', (event) => this.#keyDown(surface, event));
  }

  #pointerDown(surface, event) {
    if (event.pointerType === 'mouse' && event.button !== 0) return;  // left button only
    event.preventDefault();
    const hit = surface.hitFromEvent(event);  // read before focus/capture can change the target
    const point = surface.pointFromEvent(event);
    surface.svg.focus({ preventScroll: true });
    surface.svg.setPointerCapture(event.pointerId);  // keep receiving moves even outside the surface

    if (this.tool === 'select') {
      if (!hit) {
        this.select(null);
        return;
      }
      this.selectedUid = hit.uid;
      this.drag = { surface, uid: hit.uid, handle: hit.handle, last: point };
      this.doc.beginGesture();  // the whole drag becomes one undo step
      this.refresh();
      return;
    }

    // A drawing tool. A draft started on the other surface is abandoned.
    if (this.draft && this.draft.surface !== surface) this.draft = null;
    if (!this.draft) this.draft = { surface, kind: this.tool, points: [], cursor: point };
    this.draft.points.push(point);
    this.draft.pressedAt = [event.clientX, event.clientY];
    if (this.draft.points.length >= KINDS[this.tool].points) this.#finishDraft();
    else this.refresh();
  }

  #pointerMove(surface, event) {
    if (this.drag && this.drag.surface === surface) {
      const point = surface.pointFromEvent(event);
      const { uid, handle, last } = this.drag;
      if (handle === null) {
        this.doc.moveBy(uid, point[0] - last[0], point[1] - last[1], (moved) => surface.space.tidy(moved));
      } else {
        this.doc.setPoint(uid, handle, point);
      }
      this.drag.last = point;
    } else if (this.draft && this.draft.surface === surface) {
      this.draft.cursor = surface.pointFromEvent(event);
      this.refresh();
    }
  }

  #pointerUp(surface, event) {
    if (this.drag) {
      this.doc.endGesture();
      this.drag = null;
      this.refresh();
      return;
    }
    const draft = this.draft;
    if (!draft || draft.surface !== surface || !draft.pressedAt) return;
    // Press-drag-release: if the pointer travelled, the release point is the end point.
    // (Measured in screen pixels on purpose: it is about the hand, not the picture.)
    const travelled = Math.hypot(event.clientX - draft.pressedAt[0], event.clientY - draft.pressedAt[1]);
    draft.pressedAt = null;
    if (travelled > 6 && KINDS[draft.kind].points === 2 && draft.points.length === 1) {
      draft.points.push(surface.pointFromEvent(event));
      this.#finishDraft();
    }
  }

  #cancelPointer() {
    if (this.drag) {
      this.doc.endGesture();
      this.drag = null;
    }
    this.draft = null;
    this.refresh();
  }

  /** The half-drawn shape as something the surface can preview. */
  #draftShape() {
    const { kind, points, cursor } = this.draft;
    const shown = [...points, cursor].filter(Boolean);
    if (shown.length < 2) return null;
    // An angle with only its first point placed is previewed as a plain line.
    const previewKind = kind === 'angle' && shown.length < 3 ? 'line' : kind;
    return { uid: 'draft', layer: this.draft.surface.layer, kind: previewKind, points: shown, label: null, properties: {} };
  }

  #finishDraft() {
    const { surface, kind, points } = this.draft;
    this.draft = null;
    const uid = this.doc.add({ layer: surface.layer, kind, points, ...this.defaultsFor(kind, surface.layer) });
    this.justCreatedUid = uid;
    if (!KINDS[kind].marker) {
      // Lines, spaces, angles and text usually want a label next, so select the new shape.
      this.tool = 'select';
      this.selectedUid = uid;
    }
    this.refresh();
  }

  // ── Keyboard ───────────────────────────────────────────────────────────────
  #keyDown(surface, event) {
    const key = event.key;
    if (key === 'Escape') {
      if (this.draft) { this.draft = null; this.refresh(); } else if (this.tool !== 'select') this.setTool('select');
      else this.select(null);
      return;
    }

    const focusedShape = event.target instanceof Element ? event.target.closest('[data-uid]') : null;
    if (key === 'Enter' || key === ' ') {
      event.preventDefault();
      if (focusedShape) {
        this.tool = 'select';
        this.select(focusedShape.dataset.uid);
      } else {
        this.placeAtCentre(surface);
      }
      return;
    }

    const selected = this.selected;
    if (!selected || selected.layer !== surface.layer) return;
    if (key === 'Delete' || key === 'Backspace') {
      event.preventDefault();
      this.doc.remove(selected.uid);
      return;
    }
    const direction = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[key];
    if (direction) {
      event.preventDefault();
      const reach = event.shiftKey ? 5 : 1;
      const [stepX, stepY] = surface.space.step;
      this.doc.moveBy(selected.uid, direction[0] * stepX * reach, direction[1] * stepY * reach,
        (moved) => surface.space.tidy(moved));
    }
  }
}
