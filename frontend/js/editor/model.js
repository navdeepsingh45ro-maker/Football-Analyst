// The diagram being edited: a list of shapes, plus undo and redo.
//
// This file knows nothing about the screen. It only holds data, which is why it
// can be tested without a browser (frontend/tests/model.test.js) and why the
// drawing surfaces can simply redraw from it whenever it changes.
//
// A shape (an "annotation") is a plain object, exactly as the API stores it:
//
//   { uid: 'a1b2', layer: 'pitch', kind: 'defender', points: [[84, 27]],
//     label: 'CB', player_id: null, properties: {} }
//
// `points` are in the layer's own coordinate system (see coords.js).

/** Every kind of shape: its name in the interface and how many points define it. */
export const KINDS = {
  subject: { label: 'Studied player', points: 1, marker: true },
  attacker: { label: 'Attacker', points: 1, marker: true },
  defender: { label: 'Defender', points: 1, marker: true },
  goalkeeper: { label: 'Goalkeeper', points: 1, marker: true },
  ball: { label: 'Ball', points: 1, marker: true },
  movement: { label: 'Run', points: 2 },   // a third point, if present, bends it into a curve
  pass: { label: 'Pass', points: 2 },
  line: { label: 'Line', points: 2 },
  zone: { label: 'Space', points: 2 },     // two opposite corners
  angle: { label: 'Angle', points: 3 },    // first point, corner, third point
  text: { label: 'Text', points: 1 },
};

let uidCounter = 0;

/** A new identifier for a shape. It stays with the shape for as long as it exists. */
export function newUid() {
  uidCounter += 1;
  return `s${Date.now().toString(36)}${uidCounter.toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

const copy = (value) => JSON.parse(JSON.stringify(value));

/**
 * A shape with exactly the fields the editor works with, as an independent copy.
 * Shapes read from the API carry extras (such as z_index, their drawing order).
 * Those are dropped here: the order is simply the order of the list, and the
 * API refuses fields it does not know when the diagram is saved again.
 */
function tidyShape(shape) {
  return {
    uid: shape.uid || newUid(),
    layer: shape.layer,
    kind: shape.kind,
    points: copy(shape.points),
    label: shape.label ?? null,
    player_id: shape.player_id ?? null,
    properties: copy(shape.properties || {}),
  };
}

export class AnnotationDocument {
  #shapes = [];
  #past = [];        // earlier versions, newest last (what Undo goes back to)
  #future = [];      // versions that were undone (what Redo brings back)
  #listeners = new Set();
  #inGesture = false;

  constructor(shapes = []) {
    this.#shapes = shapes.map(tidyShape);
  }

  /** All shapes in drawing order. Treat the result as read-only; change shapes through the methods. */
  get shapes() { return this.#shapes; }

  /** The shapes of one layer ('frame' or 'pitch'). */
  onLayer(layer) { return this.#shapes.filter((shape) => shape.layer === layer); }

  find(uid) { return this.#shapes.find((shape) => shape.uid === uid) || null; }

  get canUndo() { return this.#past.length > 0; }

  get canRedo() { return this.#future.length > 0; }

  /** Be told whenever the diagram changes. Returns a function that stops the notifications. */
  onChange(listener) {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }

  #changed() {
    for (const listener of this.#listeners) listener();
  }

  /** Remember the current version so Undo can return to it. Called before every change. */
  #remember() {
    if (this.#inGesture) return;  // a gesture was remembered once, when it began
    this.#past.push(copy(this.#shapes));
    if (this.#past.length > 200) this.#past.shift();
    this.#future = [];  // a new change makes the "redo" versions obsolete
  }

  /**
   * Group many small changes into ONE undo step. Dragging a marker changes its
   * position dozens of times; without this, Undo would step back one pixel at a time.
   */
  beginGesture() {
    if (this.#inGesture) return;
    this.#remember();
    this.#inGesture = true;
  }

  endGesture() {
    if (!this.#inGesture) return;
    this.#inGesture = false;
    // A click without movement changes nothing; do not leave an empty undo step behind.
    const before = this.#past[this.#past.length - 1];
    if (before && JSON.stringify(before) === JSON.stringify(this.#shapes)) this.#past.pop();
    this.#changed();
  }

  /** Add a shape. Missing fields get defaults; returns the shape's uid. */
  add(shape) {
    this.#remember();
    const complete = tidyShape(shape);
    // The first run drawn on the pitch is taken to be the run the observation is
    // about. It can be changed afterwards (see markRecordedMovement).
    if (complete.layer === 'pitch' && complete.kind === 'movement' && !this.recordedMovement()) {
      complete.properties.recorded_movement = true;
    }
    this.#shapes.push(complete);
    this.#changed();
    return complete.uid;
  }

  /** Change fields of a shape, e.g. update(uid, { label: 'CB' }). `properties` are merged. */
  update(uid, changes) {
    const shape = this.find(uid);
    if (!shape) return;
    this.#remember();
    const { properties, ...rest } = changes;
    Object.assign(shape, copy(rest));
    if (properties) {
      for (const [name, value] of Object.entries(properties)) {
        if (value === null || value === undefined || value === '' || value === false) delete shape.properties[name];
        else shape.properties[name] = value;
      }
    }
    this.#changed();
  }

  /** Move one point of a shape. Setting point 2 of a run gives it its bend. */
  setPoint(uid, index, point) {
    const shape = this.find(uid);
    if (!shape) return;
    this.#remember();
    shape.points[index] = [point[0], point[1]];
    this.#changed();
  }

  /** Move a whole shape. `tidy` keeps each point inside its surface (see coords.js). */
  moveBy(uid, dx, dy, tidy = (point) => point) {
    const shape = this.find(uid);
    if (!shape) return;
    this.#remember();
    shape.points = shape.points.map(([x, y]) => tidy([x + dx, y + dy]));
    this.#changed();
  }

  /** Turn a curved run back into a straight one. */
  straighten(uid) {
    const shape = this.find(uid);
    if (!shape || shape.points.length < 3 || shape.kind !== 'movement') return;
    this.#remember();
    shape.points = shape.points.slice(0, 2);
    this.#changed();
  }

  remove(uid) {
    if (!this.find(uid)) return;
    this.#remember();
    this.#shapes = this.#shapes.filter((shape) => shape.uid !== uid);
    this.#changed();
  }

  /** Remove every shape, or only those of one layer. */
  clear(layer = null) {
    const remaining = layer ? this.#shapes.filter((shape) => shape.layer !== layer) : [];
    if (remaining.length === this.#shapes.length) return;
    this.#remember();
    this.#shapes = remaining;
    this.#changed();
  }

  /** The pitch run marked as "the run this observation is about", or null. */
  recordedMovement() {
    return this.#shapes.find((shape) => shape.layer === 'pitch' && shape.kind === 'movement'
      && shape.properties.recorded_movement) || null;
  }

  /** Make one pitch run THE recorded movement (or none, with uid = null). Only one can be. */
  markRecordedMovement(uid) {
    this.#remember();
    for (const shape of this.#shapes) {
      if (shape.layer !== 'pitch' || shape.kind !== 'movement') continue;
      if (shape.uid === uid) shape.properties.recorded_movement = true;
      else delete shape.properties.recorded_movement;
    }
    this.#changed();
  }

  undo() {
    if (!this.canUndo) return;
    this.#future.push(copy(this.#shapes));
    this.#shapes = this.#past.pop();
    this.#changed();
  }

  redo() {
    if (!this.canRedo) return;
    this.#past.push(copy(this.#shapes));
    this.#shapes = this.#future.pop();
    this.#changed();
  }

  /** Replace the whole diagram (when opening a saved one). Clears undo history. */
  load(shapes) {
    this.#shapes = shapes.map(tidyShape);
    this.#past = [];
    this.#future = [];
    this.#inGesture = false;
    this.#changed();
  }

  /** The shapes as the API expects them, in drawing order. */
  toJSON() {
    return copy(this.#shapes);
  }
}
