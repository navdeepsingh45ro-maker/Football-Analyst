// Drawing the pitch itself: grass, lines and a few orientation labels.
//
// Everything is in METRES, because the pitch surface's view units are metres
// (see PitchSpace in coords.js). The measurements below are the ones fixed by
// the laws of the game; only the overall length and width vary between grounds.
//
// The pitch is always drawn the same way round: the team you are studying
// attacks from left to right. Keeping that fixed is what makes "final third"
// or "left half-space" mean the same thing in every diagram you save.

import { svg } from '../dom.js';
import {
  CENTRE_CIRCLE_RADIUS, GOAL_AREA_DEPTH, GOAL_AREA_HALF_WIDTH, GOAL_WIDTH, PENALTY_AREA_DEPTH,
  PENALTY_AREA_HALF_WIDTH, PENALTY_SPOT_DISTANCE,
} from './geometry.js';

const GRASS = '#2e6b4e';
const GRASS_STRIPE = '#2a6348';
const SURROUND = '#234f3b';
const CHALK = '#f3f5f0';
const FONT = '"Avenir Next Condensed", "Roboto Condensed", "Arial Narrow", "Avenir Next", system-ui, sans-serif';

export function drawPitch(space, { showZones = false } = {}) {
  const length = space.length;
  const width = space.width;
  const margin = space.margin;
  const middle = width / 2;
  const group = svg('g', { 'pointer-events': 'none' });

  // The lines keep the same thickness on screen however large the pitch is drawn.
  const line = { fill: 'none', stroke: CHALK, 'stroke-width': 1.6, 'vector-effect': 'non-scaling-stroke' };
  const label = { 'font-family': FONT, 'font-size': 2.3, 'font-weight': 500, fill: CHALK, 'fill-opacity': 0.85 };

  group.append(svg('rect', { x: -margin, y: -margin, width: length + 2 * margin, height: width + 2 * margin, fill: SURROUND }));

  // Grass, in mown bands.
  const bands = 12;
  for (let band = 0; band < bands; band += 1) {
    group.append(svg('rect', {
      x: (band * length) / bands, y: 0, width: length / bands, height: width,
      fill: band % 2 ? GRASS_STRIPE : GRASS,
    }));
  }

  // Outline, halfway line, centre circle and spot.
  group.append(
    svg('rect', { x: 0, y: 0, width: length, height: width, ...line }),
    svg('line', { x1: length / 2, y1: 0, x2: length / 2, y2: width, ...line }),
    svg('circle', { cx: length / 2, cy: middle, r: CENTRE_CIRCLE_RADIUS, ...line }),
    svg('circle', { cx: length / 2, cy: middle, r: 0.35, fill: CHALK }),
  );

  // The same markings at both ends. `end` is the goal line; `into` is +1 or -1,
  // the direction from that goal line into the pitch.
  const arcReach = Math.sqrt(CENTRE_CIRCLE_RADIUS ** 2 - (PENALTY_AREA_DEPTH - PENALTY_SPOT_DISTANCE) ** 2);
  for (const [end, into] of [[0, 1], [length, -1]]) {
    const boxEdge = end + into * PENALTY_AREA_DEPTH;
    const spot = end + into * PENALTY_SPOT_DISTANCE;
    group.append(
      svg('rect', { x: Math.min(end, boxEdge), y: middle - PENALTY_AREA_HALF_WIDTH, width: PENALTY_AREA_DEPTH, height: 2 * PENALTY_AREA_HALF_WIDTH, ...line }),
      svg('rect', { x: Math.min(end, end + into * GOAL_AREA_DEPTH), y: middle - GOAL_AREA_HALF_WIDTH, width: GOAL_AREA_DEPTH, height: 2 * GOAL_AREA_HALF_WIDTH, ...line }),
      svg('circle', { cx: spot, cy: middle, r: 0.35, fill: CHALK }),
      // The "D": the part of a circle around the penalty spot that lies outside the box.
      svg('path', { d: `M${boxEdge} ${middle - arcReach} A${CENTRE_CIRCLE_RADIUS} ${CENTRE_CIRCLE_RADIUS} 0 0 ${into === 1 ? 1 : 0} ${boxEdge} ${middle + arcReach}`, ...line }),
      // The goal, drawn behind the goal line.
      svg('rect', { x: Math.min(end, end - into * 2), y: middle - GOAL_WIDTH / 2, width: 2, height: GOAL_WIDTH, ...line, 'stroke-opacity': 0.9 }),
    );
  }

  // Corner arcs (1 m radius).
  group.append(
    svg('path', { d: 'M1 0 A1 1 0 0 1 0 1', ...line }),
    svg('path', { d: `M${length - 1} 0 A1 1 0 0 0 ${length} 1`, ...line }),
    svg('path', { d: `M0 ${width - 1} A1 1 0 0 1 1 ${width}`, ...line }),
    svg('path', { d: `M${length} ${width - 1} A1 1 0 0 0 ${length - 1} ${width}`, ...line }),
  );

  // Orientation, written in the strip around the pitch.
  const arrowY = -margin * 0.48;
  const arrowFrom = length / 2 + 15;
  group.append(
    svg('text', { x: length / 2 + 13.5, y: arrowY, 'text-anchor': 'end', 'dominant-baseline': 'central', ...label }, 'the team you are studying attacks this way'),
    svg('line', { x1: arrowFrom, y1: arrowY, x2: arrowFrom + 8, y2: arrowY, stroke: CHALK, 'stroke-width': 0.4, 'stroke-opacity': 0.85 }),
    svg('polygon', { points: `${arrowFrom + 10},${arrowY} ${arrowFrom + 7.6},${arrowY - 1} ${arrowFrom + 7.6},${arrowY + 1}`, fill: CHALK, 'fill-opacity': 0.85 }),
    svg('text', { x: 0.5, y: arrowY, 'dominant-baseline': 'central', ...label }, 'left side'),
    svg('text', { x: 0.5, y: width + margin * 0.52, 'dominant-baseline': 'central', ...label }, 'right side'),
  );

  if (showZones) group.append(drawZoneGuides(length, width, label));
  return group;
}

/** Faint guides for the thirds and the five lanes that the reports group positions by. */
function drawZoneGuides(length, width, label) {
  const middle = width / 2;
  const guide = { stroke: CHALK, 'stroke-opacity': 0.5, 'stroke-width': 1, 'stroke-dasharray': '5 5', 'vector-effect': 'non-scaling-stroke' };
  const group = svg('g', {});
  for (const x of [length / 3, (2 * length) / 3]) {
    group.append(svg('line', { x1: x, y1: 0, x2: x, y2: width, ...guide }));
  }
  const edges = [middle - PENALTY_AREA_HALF_WIDTH, middle - GOAL_AREA_HALF_WIDTH, middle + GOAL_AREA_HALF_WIDTH, middle + PENALTY_AREA_HALF_WIDTH];
  for (const y of edges) {
    group.append(svg('line', { x1: 0, y1: y, x2: length, y2: y, ...guide }));
  }
  const small = { ...label, 'font-size': 1.9, 'fill-opacity': 0.7, 'dominant-baseline': 'central' };
  const lanes = ['left wide channel', 'left half-space', 'central channel', 'right half-space', 'right wide channel'];
  const bounds = [0, ...edges, width];
  lanes.forEach((name, index) => {
    group.append(svg('text', { x: length / 2 + 1.2, y: (bounds[index] + bounds[index + 1]) / 2, ...small }, name));
  });
  ['defensive third', 'middle third', 'final third'].forEach((name, index) => {
    group.append(svg('text', { x: (index * length) / 3 + 1.2, y: width - 1.6, ...small }, name));
  });
  return group;
}
