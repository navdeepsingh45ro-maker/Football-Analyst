// The complete drawing workspace: toolbar + surface(s) + side panels, wired together.
//
// Pages do not assemble the editor themselves. They call createWorkspace() and
// place the pieces it returns:
//
//   const workspace = createWorkspace({ frame, pitch, shapes, ... });
//   somewhere.append(workspace.element);          // toolbar, hint and the drawing surfaces
//   aside.append(workspace.panels.properties);    // + measurements, legend
//   ... later ...
//   workspace.shapes()                            // what to send to the API
//
// `frame` is { url, width, height } for a picture to draw over, or null for a
// pitch-only diagram. `pitch` is { length, width } in metres, or null for a
// frame-only one.

import { h } from '../dom.js';
import { EditorController } from './controller.js';
import { FrameSpace, PitchSpace } from './coords.js';
import { AnnotationDocument } from './model.js';
import { buildHint, buildLegend, buildMeasurements, buildProperties, buildToolbar } from './panels.js';
import { drawPitch } from './pitch.js';
import { Surface } from './surface.js';

export function createWorkspace({
  frame = null, pitch = { length: 105, width: 68 }, shapes = [],
  players = () => [], zoneTypes = [], defaultsFor, confirmClear,
}) {
  const doc = new AnnotationDocument(shapes);
  const surfaces = [];
  const boxes = [];
  let frameSurface = null;
  let pitchSurface = null;

  if (frame) {
    frameSurface = new Surface({
      space: new FrameSpace(frame.width, frame.height),
      label: 'Video frame. Draw over the picture.',
    });
    if (frame.url) frameSurface.setPicture(frame.url);
    surfaces.push(frameSurface);
    boxes.push(h('div', { class: 'surface-box', dataset: { layer: 'frame' } },
      h('div', { class: 'surface-title' }, h('strong', {}, 'Video frame'),
        h('span', {}, `${frame.width} × ${frame.height} px. Distances cannot be read from a picture.`)),
      frameSurface.element));
  }

  if (pitch) {
    const space = new PitchSpace(pitch.length, pitch.width);
    pitchSurface = new Surface({ space, label: 'Tactical pitch, seen from above. Positions are in metres.' });
    const guides = h('input', { type: 'checkbox', id: 'pitch-guides' });
    const redrawPitch = () => pitchSurface.setBackground(drawPitch(space, { showZones: guides.checked }));
    guides.addEventListener('change', redrawPitch);
    redrawPitch();
    surfaces.push(pitchSurface);
    boxes.push(h('div', { class: 'surface-box', dataset: { layer: 'pitch' } },
      h('div', { class: 'surface-title' }, h('strong', {}, 'Pitch'),
        h('span', { class: 'row' }, guides, h('label', { for: 'pitch-guides' }, 'Show thirds and lanes'))),
      pitchSurface.element));
  }

  const controller = new EditorController(doc, surfaces, { defaultsFor });

  const toolbar = buildToolbar(controller, {
    onClear: async () => {
      if (!confirmClear || await confirmClear()) doc.clear();
    },
  });
  const surfacesBox = h('div', { class: 'surfaces' }, boxes);

  // With both surfaces present, either one can be shown alone to get more room for precise drawing.
  let viewSwitch = null;
  if (frameSurface && pitchSurface) {
    const choices = [['both', 'Both'], ['frame', 'Picture only'], ['pitch', 'Pitch only']];
    const buttons = choices.map(([view, label]) => h('button', {
      type: 'button', class: 'button small', 'aria-pressed': String(view === 'both'),
      onclick: () => {
        surfacesBox.dataset.view = view;
        for (const button of buttons) button.setAttribute('aria-pressed', String(button === buttons[choices.findIndex(([name]) => name === view)]));
      },
    }, label));
    viewSwitch = h('div', { class: 'row view-switch', role: 'group', 'aria-label': 'Which drawing surfaces to show' },
      h('span', { class: 'small muted' }, 'Show'), buttons);
  }
  const element = h('div', { class: 'editor' }, toolbar, h('div', { class: 'row spread' }, buildHint(controller), viewSwitch), surfacesBox);

  // Undo/redo from the keyboard, unless you are typing in a text box (which has its own undo).
  const onKey = (event) => {
    if (!(event.metaKey || event.ctrlKey) || event.altKey) return;
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) return;
    const key = event.key.toLowerCase();
    if (key === 'z' && !event.shiftKey) { event.preventDefault(); doc.undo(); }
    else if ((key === 'z' && event.shiftKey) || key === 'y') { event.preventDefault(); doc.redo(); }
  };
  window.addEventListener('keydown', onKey);

  return {
    element,
    doc,
    controller,
    frameSurface,
    pitchSurface,
    panels: {
      properties: buildProperties(controller, { players, zoneTypes }),
      measurements: buildMeasurements(controller, {
        pitch: pitch ? { length: pitch.length, width: pitch.width } : null,
        frame: frame ? { width: frame.width, height: frame.height } : null,
      }),
      legend: buildLegend(),
    },
    /** The diagram's shapes, ready for the API. */
    shapes: () => doc.toJSON(),
    /** Call when the workspace is removed from the page. */
    destroy: () => window.removeEventListener('keydown', onKey),
  };
}

/**
 * A saved diagram, shown read-only (on a player's profile, in an observation).
 * Uses the same Surface and the same drawing code as the editor, so what you
 * saved is what you see. `snapshot` is a diagram as the API returns it.
 */
export function renderSnapshot(snapshot) {
  const doc = new AnnotationDocument(snapshot.annotations);
  const boxes = [];
  const surfaces = {};

  if (snapshot.frame_width && (snapshot.frame_image_url || doc.onLayer('frame').length)) {
    const surface = new Surface({
      space: new FrameSpace(snapshot.frame_width, snapshot.frame_height),
      label: 'Video frame with the saved drawing', interactive: false,
    });
    if (snapshot.frame_image_url) surface.setPicture(snapshot.frame_image_url);
    surface.draw(doc.onLayer('frame'));
    surfaces.frame = surface;
    boxes.push(h('div', {}, surface.element,
      snapshot.frame_image_url ? null : h('p', { class: 'small muted' }, 'No picture was saved for this frame; only the drawing.')));
  }
  if (doc.onLayer('pitch').length) {
    const space = new PitchSpace(snapshot.pitch_length_m, snapshot.pitch_width_m);
    const surface = new Surface({ space, label: 'Tactical pitch with the saved positions', interactive: false });
    surface.setBackground(drawPitch(space));
    surface.draw(doc.onLayer('pitch'));
    surfaces.pitch = surface;
    boxes.push(h('div', {}, surface.element));
  }
  const element = h('div', { class: 'diagram' }, boxes.length ? boxes : h('p', { class: 'muted' }, 'This diagram is empty.'));
  return { element, surfaces };
}
