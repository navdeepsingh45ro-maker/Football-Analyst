// Drawing shapes as SVG.
//
// One function, drawShape(), turns a stored shape into SVG elements. It is used
// everywhere a shape appears: on the drawing surfaces, in the read-only diagrams
// on a player's profile, in the toolbar icons and in the legend. So a defender
// always looks like a defender.
//
// THE VISUAL CONVENTIONS (also shown in the legend)
//   studied player   yellow circle with a ring      attacker / teammate   orange circle
//   defender         blue triangle                  goalkeeper            white square
//   ball             small white circle
//   run (no ball)    DASHED arrow                   pass                  SOLID arrow
//   line             plain line, no arrowhead       space                 hatched box
// Team is shown by SHAPE as well as colour, so nothing depends on telling
// orange from blue. Every line has a dark edge under a light stroke, so it stays
// readable on green grass and on any video picture.
//
// Sizes are multiples of `space.unit` (see coords.js), so shapes keep their
// proportions on a 105 m pitch and on a 4K frame alike. Everything is styled
// with SVG attributes rather than CSS classes, which lets a diagram be exported
// as a standalone image.

import { svg } from '../dom.js';
import { angleAt, controlPoint } from './geometry.js';
import { KINDS } from './model.js';

export const COLORS = {
  navy: '#16263f',
  chalk: '#f3f5f0',
  white: '#ffffff',
  orange: '#ee7a24',
  blue: '#2f6fd0',
  yellow: '#f5c518',
};

const FONT = '"Avenir Next Condensed", "Roboto Condensed", "Arial Narrow", "Avenir Next", system-ui, sans-serif';

const MARKER_STYLE = {
  subject: { fill: COLORS.yellow, text: COLORS.navy },
  attacker: { fill: COLORS.orange, text: COLORS.navy },
  defender: { fill: COLORS.blue, text: COLORS.white },
  goalkeeper: { fill: COLORS.white, text: COLORS.navy },
};

const fmt = (number) => Number(number.toFixed(3));
const pts = (points) => points.map(([x, y]) => `${fmt(x)},${fmt(y)}`).join(' ');

function unitVector(from, to) {
  const dx = to[0] - from[0];
  const dy = to[1] - from[1];
  const length = Math.hypot(dx, dy);
  return length < 1e-9 ? null : [dx / length, dy / length];
}

/** Text with a dark outline behind it, readable on any background. */
function haloText(text, [x, y], size, extra = {}) {
  return svg('text', {
    x: fmt(x), y: fmt(y), 'font-family': FONT, 'font-size': fmt(size), 'font-weight': 600,
    fill: COLORS.chalk, stroke: COLORS.navy, 'stroke-width': fmt(size * 0.22), 'stroke-linejoin': 'round',
    'paint-order': 'stroke', 'pointer-events': 'none', ...extra,
  }, text);
}

// ── Markers ──────────────────────────────────────────────────────────────────
function markerOutline(kind, [cx, cy], r) {
  if (kind === 'defender') {
    return svg('polygon', { points: pts([[cx, cy - 1.42 * r], [cx - 1.32 * r, cy + 0.94 * r], [cx + 1.32 * r, cy + 0.94 * r]]) });
  }
  if (kind === 'goalkeeper') {
    return svg('rect', { x: fmt(cx - 0.98 * r), y: fmt(cy - 0.98 * r), width: fmt(1.96 * r), height: fmt(1.96 * r), rx: fmt(0.16 * r) });
  }
  return svg('circle', { cx: fmt(cx), cy: fmt(cy), r: fmt(r) });
}

function drawMarker(shape, space) {
  const u = space.unit;
  const centre = space.toView(shape.points[0]);
  const [cx, cy] = centre;
  const parts = [];

  if (shape.kind === 'ball') {
    const r = 0.62 * u;
    parts.push(
      svg('circle', { cx: fmt(cx), cy: fmt(cy), r: fmt(r), fill: COLORS.white, stroke: COLORS.navy, 'stroke-width': fmt(0.24 * u) }),
      svg('circle', { cx: fmt(cx), cy: fmt(cy), r: fmt(0.2 * u), fill: COLORS.navy }),
    );
    if (shape.label) parts.push(haloText(shape.label, [cx, cy + 2.1 * u], 1.25 * u, { 'text-anchor': 'middle' }));
    return parts;
  }

  const r = 1.3 * u;
  const style = MARKER_STYLE[shape.kind];
  if (shape.kind === 'subject') {
    // The ring is what marks "the player being studied".
    parts.push(
      svg('circle', { cx: fmt(cx), cy: fmt(cy), r: fmt(1.62 * r), fill: 'none', stroke: COLORS.navy, 'stroke-width': fmt(0.52 * u) }),
      svg('circle', { cx: fmt(cx), cy: fmt(cy), r: fmt(1.62 * r), fill: 'none', stroke: COLORS.yellow, 'stroke-width': fmt(0.28 * u) }),
    );
  }
  // A light edge under the dark outline lifts the marker off dark pictures.
  const casing = markerOutline(shape.kind, centre, r);
  casing.setAttribute('fill', 'none');
  casing.setAttribute('stroke', COLORS.chalk);
  casing.setAttribute('stroke-width', fmt(0.62 * u));
  casing.setAttribute('stroke-linejoin', 'round');
  const body = markerOutline(shape.kind, centre, r);
  body.setAttribute('fill', style.fill);
  body.setAttribute('stroke', COLORS.navy);
  body.setAttribute('stroke-width', fmt(0.24 * u));
  body.setAttribute('stroke-linejoin', 'round');
  parts.push(casing, body);

  const label = shape.label || '';
  if (label && label.length <= 3) {
    // Short labels (a shirt number, "CB") go inside the marker.
    const size = (label.length === 3 ? 1.1 : 1.42) * u;
    const textY = shape.kind === 'defender' ? cy + 0.22 * r : cy;
    parts.push(svg('text', {
      x: fmt(cx), y: fmt(textY), 'text-anchor': 'middle', 'dominant-baseline': 'central', 'font-family': FONT,
      'font-size': fmt(size), 'font-weight': 700, fill: style.text, 'pointer-events': 'none',
    }, label));
  } else if (label) {
    parts.push(haloText(label, [cx, cy + 2.75 * u], 1.25 * u, { 'text-anchor': 'middle' }));
  }
  return parts;
}

// ── Lines and arrows ─────────────────────────────────────────────────────────
function arrowHead(tip, direction, u) {
  const length = 1.75 * u;
  const half = 0.78 * u;
  const base = [tip[0] - direction[0] * length, tip[1] - direction[1] * length];
  const across = [-direction[1], direction[0]];
  return svg('polygon', {
    points: pts([tip, [base[0] + across[0] * half, base[1] + across[1] * half], [base[0] - across[0] * half, base[1] - across[1] * half]]),
    fill: COLORS.chalk, stroke: COLORS.navy, 'stroke-width': fmt(0.16 * u), 'stroke-linejoin': 'round',
  });
}

/** A line with a dark edge under a light stroke, plus an invisible wide stroke that is easy to click. */
function casedPath(d, u, { dash = null, width = 0.3, color = COLORS.chalk } = {}) {
  return [
    svg('path', { d, fill: 'none', stroke: COLORS.navy, 'stroke-width': fmt((width + 0.3) * u), 'stroke-linecap': 'round', opacity: 0.9 }),
    svg('path', { d, fill: 'none', stroke: color, 'stroke-width': fmt(width * u), 'stroke-linecap': dash ? 'butt' : 'round', 'stroke-dasharray': dash }),
    svg('path', { d, fill: 'none', stroke: COLORS.navy, 'stroke-opacity': 0, 'stroke-width': fmt(2 * u), 'pointer-events': 'stroke', 'data-export': 'skip' }),
  ];
}

function drawLine(shape, space) {
  const u = space.unit;
  const [start, end] = shape.points.slice(0, 2).map((point) => space.toView(point));
  const through = shape.points[2] ? space.toView(shape.points[2]) : null;
  const parts = [];

  let d;
  let endDirection;
  if (through) {
    const control = controlPoint(start, end, through);
    d = `M${fmt(start[0])} ${fmt(start[1])} Q${fmt(control[0])} ${fmt(control[1])} ${fmt(end[0])} ${fmt(end[1])}`;
    endDirection = unitVector(control, end) || unitVector(start, end);
  } else {
    d = `M${fmt(start[0])} ${fmt(start[1])} L${fmt(end[0])} ${fmt(end[1])}`;
    endDirection = unitVector(start, end);
  }

  if (shape.kind === 'movement') {
    parts.push(...casedPath(d, u, { dash: `${fmt(1.15 * u)} ${fmt(0.8 * u)}` }));  // dashed = a run
  } else if (shape.kind === 'pass') {
    parts.push(...casedPath(d, u));                                              // solid = a pass
  } else {
    parts.push(...casedPath(d, u, { width: 0.24 }));                             // plain line
  }
  if (shape.kind !== 'line' && endDirection) parts.push(arrowHead(end, endDirection, u));

  if (shape.label) {
    const middle = through || [(start[0] + end[0]) / 2, (start[1] + end[1]) / 2];
    parts.push(haloText(shape.label, [middle[0], middle[1] - 0.9 * u], 1.3 * u, { 'text-anchor': 'middle' }));
  }
  return parts;
}

// ── Highlighted space ────────────────────────────────────────────────────────
function drawZone(shape, space) {
  const u = space.unit;
  const [a, b] = shape.points.map((point) => space.toView(point));
  const x0 = Math.min(a[0], b[0]);
  const x1 = Math.max(a[0], b[0]);
  const y0 = Math.min(a[1], b[1]);
  const y1 = Math.max(a[1], b[1]);

  // Diagonal hatching, worked out line by line so no SVG pattern (and no id) is needed.
  // Each hatch line is x + y = c; it is cut to the part that lies inside the box.
  const gap = 1.7 * u;
  let hatch = '';
  for (let c = x0 + y0 + gap; c < x1 + y1; c += gap) {
    const fromX = Math.max(x0, c - y1);
    const toX = Math.min(x1, c - y0);
    if (toX > fromX) hatch += `M${fmt(fromX)} ${fmt(c - fromX)} L${fmt(toX)} ${fmt(c - toX)} `;
  }

  const parts = [
    svg('rect', { x: fmt(x0), y: fmt(y0), width: fmt(x1 - x0), height: fmt(y1 - y0), fill: COLORS.yellow, 'fill-opacity': 0.2 }),
    svg('path', { d: hatch, stroke: COLORS.yellow, 'stroke-width': fmt(0.14 * u), 'stroke-opacity': 0.75, fill: 'none', 'pointer-events': 'none' }),
    svg('rect', { x: fmt(x0), y: fmt(y0), width: fmt(x1 - x0), height: fmt(y1 - y0), fill: 'none', stroke: COLORS.navy, 'stroke-width': fmt(0.5 * u), opacity: 0.85 }),
    svg('rect', { x: fmt(x0), y: fmt(y0), width: fmt(x1 - x0), height: fmt(y1 - y0), fill: 'none', stroke: COLORS.yellow, 'stroke-width': fmt(0.24 * u), 'stroke-dasharray': `${fmt(0.9 * u)} ${fmt(0.6 * u)}` }),
  ];
  const caption = shape.label || shape.properties.zone_type;
  if (caption) {
    // A box in the right half of the picture gets its caption right-aligned, so a
    // long caption grows towards the middle instead of running off the edge.
    const onRight = space.view && (x0 + x1) / 2 > space.view.x + space.view.width / 2;
    parts.push(haloText(caption, [onRight ? x1 - 0.6 * u : x0 + 0.6 * u, y0 + 1.6 * u], 1.25 * u,
      onRight ? { 'text-anchor': 'end' } : {}));
  }
  return parts;
}

// ── Angle ────────────────────────────────────────────────────────────────────
function drawAngle(shape, space) {
  const u = space.unit;
  const [first, corner, third] = shape.points.map((point) => space.toView(point));
  const parts = [
    ...casedPath(`M${fmt(first[0])} ${fmt(first[1])} L${fmt(corner[0])} ${fmt(corner[1])} L${fmt(third[0])} ${fmt(third[1])}`,
      u, { width: 0.22, color: COLORS.yellow }),
  ];
  // Measured in VIEW units, where a frame is in real pixels and the pitch in metres.
  const value = angleAt(corner, first, third);
  const toFirst = unitVector(corner, first);
  const toThird = unitVector(corner, third);
  let labelAt = [corner[0], corner[1] - 2.2 * u];

  if (value !== null && toFirst && toThird) {
    const radius = 2.6 * u;
    const arcStart = [corner[0] + toFirst[0] * radius, corner[1] + toFirst[1] * radius];
    const arcEnd = [corner[0] + toThird[0] * radius, corner[1] + toThird[1] * radius];
    const clockwise = toFirst[0] * toThird[1] - toFirst[1] * toThird[0] > 0 ? 1 : 0;
    parts.push(svg('path', {
      d: `M${fmt(arcStart[0])} ${fmt(arcStart[1])} A${fmt(radius)} ${fmt(radius)} 0 0 ${clockwise} ${fmt(arcEnd[0])} ${fmt(arcEnd[1])}`,
      fill: 'none', stroke: COLORS.yellow, 'stroke-width': fmt(0.2 * u), 'pointer-events': 'none',
    }));
    // Put the number on the line that splits the angle in half, just outside the arc.
    const bisector = unitVector([0, 0], [toFirst[0] + toThird[0], toFirst[1] + toThird[1]]) || [-toFirst[1], toFirst[0]];
    labelAt = [corner[0] + bisector[0] * 4.6 * u, corner[1] + bisector[1] * 4.6 * u];
  }
  const text = value === null ? 'angle undefined' : `${value.toFixed(1)}°`;
  parts.push(haloText(shape.label ? `${shape.label} ${text}` : text, labelAt, 1.4 * u,
    { 'text-anchor': 'middle', 'dominant-baseline': 'central' }));
  return parts;
}

function drawText(shape, space) {
  const u = space.unit;
  return [haloText(shape.label || 'Text', space.toView(shape.points[0]), 1.7 * u, { 'pointer-events': 'auto' })];
}

// ── The public pieces ────────────────────────────────────────────────────────
function describe(shape, space) {
  const name = KINDS[shape.kind].label + (shape.label ? ` ${shape.label}` : '');
  return `${name}, ${space.describe(shape.points[0])}`;
}

/**
 * Draw one shape. Returns a <g> that carries the shape's uid, can receive
 * keyboard focus, and describes itself to screen readers.
 */
export function drawShape(shape, space, { interactive = false } = {}) {
  let parts;
  if (KINDS[shape.kind].marker) parts = drawMarker(shape, space);
  else if (shape.kind === 'zone') parts = drawZone(shape, space);
  else if (shape.kind === 'angle') parts = drawAngle(shape, space);
  else if (shape.kind === 'text') parts = drawText(shape, space);
  else parts = drawLine(shape, space);

  const attributes = { 'data-uid': shape.uid, 'data-kind': shape.kind };
  if (interactive) {
    Object.assign(attributes, { tabindex: 0, role: 'button', 'aria-label': describe(shape, space) });
  }
  return svg('g', attributes, svg('title', {}, describe(shape, space)), parts);
}

/**
 * What marks the selected shape. A marker gets a dashed ring (a handle on its
 * centre would hide its number, and you move it by dragging the marker itself).
 * Everything else gets a square handle per point, plus a round one to bend a run.
 */
export function drawHandles(shape, space) {
  const u = space.unit;
  const size = 0.95 * u;
  if (KINDS[shape.kind].marker) {
    const [x, y] = space.toView(shape.points[0]);
    const radius = (shape.kind === 'ball' ? 1.5 : 2.75) * u;
    const ring = { cx: fmt(x), cy: fmt(y), r: fmt(radius), fill: 'none', 'pointer-events': 'none', 'data-export': 'skip' };
    return [
      svg('circle', { ...ring, stroke: COLORS.navy, 'stroke-width': fmt(0.42 * u) }),
      svg('circle', { ...ring, stroke: COLORS.yellow, 'stroke-width': fmt(0.22 * u), 'stroke-dasharray': `${fmt(0.8 * u)} ${fmt(0.55 * u)}` }),
    ];
  }
  const handles = shape.points.slice(0, 2 + (shape.kind === 'angle' ? 1 : 0)).map((point, index) => {
    const [x, y] = space.toView(point);
    return svg('rect', {
      x: fmt(x - size / 2), y: fmt(y - size / 2), width: fmt(size), height: fmt(size),
      fill: COLORS.yellow, stroke: COLORS.navy, 'stroke-width': fmt(0.18 * u),
      'data-uid': shape.uid, 'data-handle': index, 'data-export': 'skip',
    });
  });
  if (shape.kind === 'movement') {
    const [start, end] = shape.points.map((point) => space.toView(point));
    const through = shape.points[2] ? space.toView(shape.points[2]) : [(start[0] + end[0]) / 2, (start[1] + end[1]) / 2];
    handles.push(svg('circle', {
      cx: fmt(through[0]), cy: fmt(through[1]), r: fmt(0.55 * u),
      fill: shape.points[2] ? COLORS.yellow : COLORS.white, stroke: COLORS.navy, 'stroke-width': fmt(0.18 * u),
      'data-uid': shape.uid, 'data-handle': 2, 'data-export': 'skip',
    }, svg('title', {}, 'Drag to bend the run')));
  }
  return handles;
}

// A tiny coordinate system for icons: stored points are already view units.
const ICON_SPACE = (unit) => ({ unit, toView: (point) => point, describe: () => '' });

const ICON_SAMPLES = {
  subject: { points: [[20, 14]], label: '9', unit: 4.6 },
  attacker: { points: [[20, 14]], unit: 6.4 },
  defender: { points: [[20, 14.5]], unit: 6 },
  goalkeeper: { points: [[20, 14]], label: 'GK', unit: 6.4 },
  ball: { points: [[20, 14]], unit: 8.5 },
  movement: { points: [[5, 21], [35, 7]], unit: 5.2 },
  pass: { points: [[5, 21], [35, 7]], unit: 5.2 },
  line: { points: [[5, 21], [35, 7]], unit: 5.2 },
  zone: { points: [[6, 5], [34, 23]], unit: 4.2 },
  angle: { points: [[35, 23], [7, 23], [30, 5]], unit: 4.4 },
  text: { points: [[9, 20]], label: 'Aa', unit: 8 },
};

/** A small picture of a kind of shape, for tool buttons and the legend. */
export function shapeIcon(kind) {
  const sample = ICON_SAMPLES[kind];
  const shape = { uid: `icon-${kind}`, kind, points: sample.points, label: sample.label || null, properties: {} };
  const icon = svg('svg', { viewBox: '0 0 40 28', 'aria-hidden': 'true', focusable: 'false' });
  const group = drawShape(shape, ICON_SPACE(sample.unit));
  // Icons are decoration: drop the tooltip and anything only meant for clicking.
  group.querySelector('title').remove();
  group.querySelectorAll('[data-export="skip"]').forEach((node) => node.remove());
  if (kind === 'angle') group.querySelector('text').remove();
  icon.append(group);
  return icon;
}

/**
 * A "magnet": a marker in miniature, used in lists (lineups, player tables).
 *   magnet('attacker', '9')   magnet('goalkeeper', 'GK')
 */
export function magnet(kind, label = '', { large = false } = {}) {
  const shape = { uid: 'magnet', kind, points: [[15, kind === 'defender' ? 16 : 15]], label: String(label || '').slice(0, 3) || null, properties: {} };
  const icon = svg('svg', { viewBox: '0 0 30 30', class: large ? 'magnet large' : 'magnet', 'aria-hidden': 'true', focusable: 'false' });
  const group = drawShape(shape, ICON_SPACE(kind === 'subject' ? 5.6 : 8));
  group.querySelector('title').remove();
  icon.append(group);
  return icon;
}
