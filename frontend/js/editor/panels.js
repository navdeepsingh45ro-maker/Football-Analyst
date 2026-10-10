// The editor's controls around the drawing: toolbar, hint line, the panel for
// the selected shape, the measurements and the legend.
//
// Each build...() function returns an element and keeps it up to date by
// listening to the controller. None of them changes the diagram directly; they
// call the document's methods (model.js), so undo and redo cover everything.

import { clear, h, svg } from '../dom.js';
import { measureFrame, measurePitch } from './measure.js';
import { KINDS } from './model.js';
import { shapeIcon } from './render.js';

const TOOLS = [
  // [kind, short label under the icon, full description]
  ['subject', 'Studied', 'Marker for the player you are studying'],
  ['attacker', 'Attacker', 'Attacking player marker (a teammate when your player attacks)'],
  ['defender', 'Defender', 'Defending player marker (an opponent when your player attacks)'],
  ['goalkeeper', 'Keeper', 'Goalkeeper marker'],
  ['ball', 'Ball', 'Ball marker'],
  ['movement', 'Run', 'Movement arrow: a run without the ball'],
  ['pass', 'Pass', 'Passing direction'],
  ['line', 'Line', 'Straight line'],
  ['zone', 'Space', 'Highlighted space or zone'],
  ['angle', 'Angle', 'Angle measurement between three points'],
  ['text', 'Text', 'Text annotation'],
];

const LEGEND = [
  ['subject', 'Studied player: ringed yellow circle'],
  ['attacker', 'Attacker or teammate: orange circle'],
  ['defender', 'Defender or opponent: blue triangle'],
  ['goalkeeper', 'Goalkeeper: white square'],
  ['ball', 'Ball: small white circle'],
  ['movement', 'Run without the ball: dashed arrow'],
  ['pass', 'Pass: solid arrow'],
  ['line', 'Line: no arrowhead'],
  ['zone', 'Space: hatched yellow box'],
  ['angle', 'Angle: two lines, arc and degrees'],
];

const POINT_NAMES = {
  movement: ['Start', 'End', 'Bend'],
  pass: ['From', 'To'],
  line: ['One end', 'Other end'],
  zone: ['Corner', 'Opposite corner'],
  angle: ['One end', 'Corner', 'Other end'],
};

/** A line-drawn icon that takes the button's text colour. */
function glyph(...paths) {
  return svg('svg', { viewBox: '0 0 40 28', 'aria-hidden': 'true', focusable: 'false' },
    paths.map((d) => svg('path', {
      d, fill: d.endsWith('Z') ? 'currentColor' : 'none', stroke: 'currentColor',
      'stroke-width': 2.2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round',
    })));
}

const GLYPHS = {
  select: () => glyph('M15 4 L15 22 L19.5 18 L22.5 24.5 L25 23.3 L22 17 L28 17 Z'),
  undo: () => glyph('M12 11 H25 a6 6 0 0 1 0 12 H17', 'M16.5 6 L11.5 11 L16.5 16'),
  redo: () => glyph('M28 11 H15 a6 6 0 0 0 0 12 H23', 'M23.5 6 L28.5 11 L23.5 16'),
  remove: () => glyph('M12 9 H28', 'M17 9 V5.5 H23 V9', 'M14.5 9 L15.8 23 H24.2 L25.5 9'),
  clear: () => glyph('M13 7 L27 21', 'M27 7 L13 21'),
};

export function buildToolbar(controller, { onClear }) {
  const doc = controller.doc;
  const toolButtons = new Map();

  const toolButton = (name, label, description, icon) => {
    const button = h('button', {
      type: 'button', class: 'tool', title: description, 'aria-label': description, 'aria-pressed': 'false',
      onclick: () => controller.setTool(name),
    }, icon, h('span', {}, label));
    toolButtons.set(name, button);
    return button;
  };
  const actionButton = (label, description, icon, action) => h('button', {
    type: 'button', class: 'tool', title: description, 'aria-label': description, onclick: action,
  }, icon, h('span', {}, label));

  const undo = actionButton('Undo', 'Undo the last change (Ctrl/Cmd + Z)', GLYPHS.undo(), () => doc.undo());
  const redo = actionButton('Redo', 'Redo (Ctrl/Cmd + Shift + Z)', GLYPHS.redo(), () => doc.redo());
  const remove = actionButton('Delete', 'Delete the selected shape (Delete key)', GLYPHS.remove(), () => controller.deleteSelected());
  const clearAll = actionButton('Clear', 'Remove every shape from the diagram', GLYPHS.clear(), onClear);

  const element = h('div', { class: 'tools', role: 'toolbar', 'aria-label': 'Drawing tools' },
    toolButton('select', 'Select', 'Select, move and edit shapes', GLYPHS.select()),
    h('span', { class: 'tool-gap' }),
    TOOLS.map(([kind, label, description]) => toolButton(kind, label, description, shapeIcon(kind))),
    h('span', { class: 'tool-gap' }),
    undo, redo, remove, clearAll,
  );

  const update = () => {
    for (const [name, button] of toolButtons) button.setAttribute('aria-pressed', String(controller.tool === name));
    undo.disabled = !doc.canUndo;
    redo.disabled = !doc.canRedo;
    remove.disabled = !controller.selected;
    clearAll.disabled = doc.shapes.length === 0;
  };
  controller.onState(update);
  update();
  return element;
}

/** One line under the toolbar that says how the current tool works. */
export function buildHint(controller) {
  const element = h('p', { class: 'hint', role: 'status' });
  const update = () => {
    const keyboard = controller.tool === 'select' ? '' : ' Without a mouse: focus the drawing and press Enter to place it in the middle.';
    element.textContent = controller.hint + keyboard;
  };
  controller.onState(update);
  update();
  return element;
}

/**
 * The panel for the selected shape: label, linked player, exact coordinates.
 *
 * @param players    () => [{ id, full_name, shirt_number }] offered for linking a marker
 * @param zoneTypes  the suggested kinds of space
 */
export function buildProperties(controller, { players = () => [], zoneTypes = [] } = {}) {
  const doc = controller.doc;
  const element = h('div', { class: 'panel' });

  // HOW THIS PANEL STAYS IN STEP WITHOUT GETTING IN YOUR WAY
  // It is BUILT only when its layout must change: another shape is selected, a
  // run gains or loses its bend, or the list of players changes. For every other
  // change (dragging, nudging, typing) only the VALUES of its boxes are refreshed,
  // and never the box you are typing in. Rebuilding on every change would destroy
  // the box the cursor is in, or the one you are tabbing to.
  let builtFor = null;     // describes what the current layout was built for
  let syncValues = [];     // functions that copy the shape's current values into the boxes

  const render = () => {
    const selected = controller.selected;
    const layout = selected
      ? `${selected.uid}|${selected.points.length}|${players().map((player) => player.id).join(',')}`
      : '';
    if (layout === builtFor) {
      for (const sync of syncValues) sync();
      return;
    }
    builtFor = layout;
    syncValues = [];
    clear(element);

    if (!selected) {
      element.append(h('h3', {}, 'Selected shape'),
        h('p', { class: 'muted small' }, 'Nothing selected. With the Select tool, press a shape to label it, link it '
          + 'to a player or type exact coordinates.'));
      return;
    }

    const uid = selected.uid;
    const kind = selected.kind;
    // Always look the shape up again: after an undo it is a different object.
    const shape = () => doc.find(uid);
    const surface = controller.surfaceFor(selected.layer);
    const isMarker = KINDS[kind].marker;
    const onPitch = selected.layer === 'pitch';
    const untouched = (input) => document.activeElement !== input;
    const fields = [];

    // Label. Typing is grouped into one undo step from focus to blur.
    const labelInput = h('input', {
      type: 'text', id: 'shape-label', maxLength: 120, placeholder: isMarker ? 'e.g. 9 or CB' : '',
      onfocus: () => doc.beginGesture(),
      oninput: () => doc.update(uid, { label: labelInput.value.trim() || null }),
      onblur: () => doc.endGesture(),
    });
    syncValues.push(() => { if (untouched(labelInput)) labelInput.value = shape().label || ''; });
    fields.push(h('div', { class: 'field' },
      h('label', { for: 'shape-label' }, kind === 'text' ? 'Text' : (isMarker ? 'Number or initials' : 'Label')),
      labelInput));

    if (isMarker && kind !== 'ball') {
      const select = h('select', {
        id: 'shape-player',
        onchange: () => {
          const player = players().find((candidate) => String(candidate.id) === select.value) || null;
          const changes = { player_id: player ? player.id : null };
          if (player && !shape().label) changes.label = suggestLabel(player);
          doc.update(uid, changes);
        },
      }, h('option', { value: '' }, 'Not linked to a player'),
      players().map((player) => h('option', { value: player.id }, player.full_name)));
      syncValues.push(() => { select.value = shape().player_id === null ? '' : String(shape().player_id); });
      fields.push(h('div', { class: 'field' }, h('label', { for: 'shape-player' }, 'Stands for'), select));
    }

    if (kind === 'zone') {
      const select = h('select', {
        id: 'shape-zone',
        onchange: () => doc.update(uid, { properties: { zone_type: select.value } }),
      }, h('option', { value: '' }, 'Not specified'), zoneTypes.map((type) => h('option', { value: type }, type)));
      syncValues.push(() => { select.value = shape().properties.zone_type || ''; });
      fields.push(h('div', { class: 'field' }, h('label', { for: 'shape-zone' }, 'Kind of space'), select));
    }

    if (kind === 'movement' && onPitch) {
      const box = h('input', {
        type: 'checkbox', id: 'shape-recorded',
        onchange: () => doc.markRecordedMovement(box.checked ? uid : null),
      });
      syncValues.push(() => { box.checked = Boolean(shape().properties.recorded_movement); });
      fields.push(h('div', { class: 'field check' }, box,
        h('label', { for: 'shape-recorded' }, 'This is the run I am recording')),
      h('p', { class: 'field small muted' }, 'The reports use this arrow\'s start and end to say where on the pitch '
        + 'the movement happened.'));
    }

    // Exact coordinates: the way to position a shape without dragging.
    // The pitch is shown in metres; a picture in percent (stored as a 0-1 fraction).
    const names = POINT_NAMES[kind] || ['Position'];
    const axisNames = onPitch
      ? ['distance from own goal line, metres', 'distance from left touchline, metres']
      : ['across, % of the picture', 'down, % of the picture'];
    const toShown = (value) => Number((onPitch ? value : value * 100).toFixed(onPitch ? 2 : 1));
    const grid = h('div', { class: 'point-inputs' });
    selected.points.forEach((_point, index) => {
      const inputs = [0, 1].map((axis) => h('input', {
        type: 'number', step: 0.5, 'aria-label': `${names[index] || 'Point'} ${axisNames[axis]}`,
        onchange: () => {
          const typed = inputs.map((input) => Number(input.value));
          if (inputs.some((input) => input.value.trim() === '') || typed.some((value) => !Number.isFinite(value))) return;
          doc.setPoint(uid, index, surface.space.tidy(onPitch ? typed : [typed[0] / 100, typed[1] / 100]));
        },
      }));
      syncValues.push(() => {
        const point = shape().points[index];
        inputs.forEach((input, axis) => { if (untouched(input)) input.value = toShown(point[axis]); });
      });
      grid.append(h('span', {}, names[index] || 'Point'), ...inputs);
    });
    fields.push(h('fieldset', { class: 'field' },
      h('legend', {}, onPitch ? 'Position in metres (from own goal line, from left touchline)' : 'Position in % of the picture (across, down)'),
      grid));

    const buttons = [];
    if (kind === 'movement' && selected.points.length > 2) {
      buttons.push(h('button', { type: 'button', class: 'button small', onclick: () => doc.straighten(uid) }, 'Straighten run'));
    }
    buttons.push(h('button', { type: 'button', class: 'button small', onclick: () => controller.deleteSelected() }, 'Delete shape'));

    element.append(
      h('h3', {}, `${KINDS[kind].label} on the ${onPitch ? 'pitch' : 'picture'}`),
      h('div', { class: 'form-grid' }, fields),
      h('div', { class: 'row' }, buttons),
    );
    for (const sync of syncValues) sync();

    // A new piece of text is typed straight away, so put the cursor in its box.
    if (controller.justCreatedUid === uid) {
      controller.justCreatedUid = null;
      if (kind === 'text') { labelInput.focus(); labelInput.select(); }
    }
  };

  controller.onState(render);
  render();
  return element;
}

/** A shirt number if known, otherwise initials: "Sam Finisher" -> "SF". */
function suggestLabel(player) {
  if (player.shirt_number) return String(player.shirt_number);
  return player.full_name.split(/\s+/).filter(Boolean).map((word) => word[0].toUpperCase()).slice(0, 3).join('');
}

/** Distances and angles read off the diagram, kept up to date as you draw. */
export function buildMeasurements(controller, { pitch, frame }) {
  const list = h('ul', { class: 'measures' });
  const element = h('div', { class: 'panel' }, h('details', { open: true },
    h('summary', {}, 'Measurements'),
    h('p', { class: 'small muted' }, 'Estimates. They are only as accurate as the positions you placed by eye.'),
    list));

  const update = () => {
    const selected = controller.selected;
    const findings = [
      ...(pitch ? measurePitch(controller.doc.shapes, pitch, selected ? selected.uid : null) : []),
      ...(frame ? measureFrame(controller.doc.shapes, frame) : []),
    ];
    clear(list);
    if (!findings.length) {
      list.append(h('li', { class: 'muted' }, pitch
        ? 'Place the studied player, the ball, a run or an angle on the pitch to see distances and angles.'
        : 'Draw an angle to measure it. A picture cannot give real distances; use the pitch for those.'));
      return;
    }
    for (const finding of findings) {
      list.append(h('li', {}, h('div', {}, finding.title, ': ', h('span', { class: 'value' }, finding.value)),
        h('div', { class: 'muted' }, finding.detail)));
    }
  };
  controller.onState(update);
  update();
  return element;
}

/** What every symbol and line style means. */
export function buildLegend() {
  return h('div', { class: 'panel' }, h('details', { open: true },
    h('summary', {}, 'Legend'),
    h('ul', { class: 'legend' }, LEGEND.map(([kind, text]) => h('li', {}, shapeIcon(kind), h('span', {}, text)))),
    h('p', { class: 'small muted' }, 'Arrows, lines and spaces record what YOU saw and how you read it. They are not '
      + 'tracking data, and drawing a space does not mean the app has detected one.')));
}
