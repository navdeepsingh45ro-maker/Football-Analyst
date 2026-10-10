// Measurements read off a diagram, in words the panel can show directly.
//
// Pure functions: a list of shapes in, a list of findings out. Each finding says
// WHAT was measured and BETWEEN WHICH points, because a bare number such as
// "37 degrees" is meaningless without knowing which angle it is.
//
//   { title: 'Run', value: '15.4 m', detail: 'forward and to the left ...' }
//
// PITCH LAYER: positions are metres, so distances and angles are real estimates.
// FRAME LAYER: a camera picture is distorted by perspective. No distance can be
// read from it at all, and an angle drawn on it is the angle ON THE PICTURE, not
// the angle on the grass. The findings say so.

import {
  angleAt, describeDirection, directionDegrees, distance, distancesToBoundaries, goalMouthAngle,
  pathLength, pitchZone,
} from './geometry.js';

const metres = (value) => `${value.toFixed(1)} m`;
const degrees = (value) => (value === null ? 'undefined' : `${value.toFixed(1)}°`);
const nameOf = (shape, fallback) => (shape.label ? `${fallback} ${shape.label}` : fallback);

function zoneText(point, pitch) {
  const zone = pitchZone(point, pitch.length, pitch.width);
  if (!zone.on_pitch) return 'off the pitch';
  return [zone.third, zone.lane, zone.area].filter(Boolean).join(', ');
}

function bearingText(from, to) {
  const direction = directionDegrees(from, to);
  return direction === null ? 'same spot' : describeDirection(direction);
}

/**
 * Everything worth reading off the pitch layer.
 * `pitch` is { length, width } in metres. `focusUid` optionally names the marker
 * to measure from; otherwise the studied player's marker is used.
 */
export function measurePitch(shapes, pitch, focusUid = null) {
  const onPitch = shapes.filter((shape) => shape.layer === 'pitch');
  const findings = [];
  const ball = onPitch.find((shape) => shape.kind === 'ball');
  const markers = onPitch.filter((shape) => ['subject', 'attacker', 'defender', 'goalkeeper'].includes(shape.kind));
  const focus = markers.find((shape) => shape.uid === focusUid) || onPitch.find((shape) => shape.kind === 'subject');

  if (focus) {
    const here = focus.points[0];
    const who = focus.kind === 'subject' ? nameOf(focus, 'Studied player') : nameOf(focus, focus.kind);
    const edges = distancesToBoundaries(here, pitch.length, pitch.width);
    findings.push({
      title: `${who}: position`,
      value: zoneText(here, pitch),
      detail: `${metres(edges.own_goal_line)} from own goal line, ${metres(edges.opponent_goal_line)} from the goal `
        + `line attacked; ${metres(edges.left_touchline)} from the left touchline, ${metres(edges.right_touchline)} `
        + 'from the right.',
    });

    if (ball) {
      findings.push({
        title: `${who} to the ball`,
        value: metres(distance(here, ball.points[0])),
        detail: `The ball is ${bearingText(here, ball.points[0])} from the player.`,
      });
    }

    const others = (kind) => markers
      .filter((shape) => shape.kind === kind && shape.uid !== focus.uid)
      .map((shape) => ({ shape, gap: distance(here, shape.points[0]) }))
      .sort((a, b) => a.gap - b.gap);

    const defenders = others('defender');
    if (defenders.length) {
      findings.push({
        title: `${who} to defenders`,
        value: `nearest ${metres(defenders[0].gap)}`,
        detail: defenders.slice(0, 4)
          .map(({ shape, gap }) => `${nameOf(shape, 'defender')}: ${metres(gap)}, ${bearingText(here, shape.points[0])}`)
          .join('. ') + '.',
      });
    }
    const teammates = [...others('attacker'), ...(focus.kind === 'subject' ? [] : others('subject'))];
    if (teammates.length) {
      findings.push({
        title: `${who} to teammates`,
        value: `nearest ${metres(teammates[0].gap)}`,
        detail: teammates.slice(0, 4)
          .map(({ shape, gap }) => `${nameOf(shape, 'teammate')}: ${metres(gap)}, ${bearingText(here, shape.points[0])}`)
          .join('. ') + '.',
      });
    }

    const goalCentre = [pitch.length, pitch.width / 2];
    const mouth = goalMouthAngle(here, pitch.length, pitch.width);
    findings.push({
      title: `${who} to the goal attacked`,
      value: metres(distance(here, goalCentre)),
      detail: `From here the goal spans ${degrees(mouth)}: the angle at the player between the two posts. `
        + 'That is geometry only. It ignores the goalkeeper and defenders, and it is not a passing angle.',
    });

    if (ball) {
      const opening = angleAt(here, ball.points[0], goalCentre);
      findings.push({
        title: `${who}: ball and goal`,
        value: degrees(opening),
        detail: 'The angle at the player between the line to the ball and the line to the centre of the goal. '
          + 'It describes positions only; the diagram does not know which way the player was facing.',
      });
    }
  }

  for (const shape of onPitch) {
    if (shape.kind === 'movement' || shape.kind === 'pass') {
      const [start, end, through] = shape.points;
      const direction = directionDegrees(start, end);
      const along = pathLength(shape.points);
      const what = shape.kind === 'movement' ? 'Run' : 'Pass';
      const recorded = shape.properties.recorded_movement ? ' (the recorded movement)' : '';
      let detail = direction === null
        ? 'Start and end are the same point, so it has no direction.'
        : `Direction: ${describeDirection(direction)} (${direction.toFixed(0)}° from straight at goal; `
          + `positive is to the right). From ${zoneText(start, pitch)} to ${zoneText(end, pitch)}.`;
      if (through) detail += ` Curved: ${metres(distance(start, end))} in a straight line.`;
      if (shape.kind === 'movement') detail += ' This is the direction of travel you drew, not where the player was facing.';
      findings.push({ title: nameOf(shape, what) + recorded, value: metres(along), detail });
    } else if (shape.kind === 'line') {
      findings.push({ title: nameOf(shape, 'Line'), value: metres(distance(shape.points[0], shape.points[1])),
        detail: 'Length of the line.' });
    } else if (shape.kind === 'angle') {
      const [first, corner, third] = shape.points;
      const value = angleAt(corner, first, third);
      findings.push({
        title: nameOf(shape, 'Angle'),
        value: degrees(value),
        detail: value === null
          ? 'Undefined: one of the outer points sits exactly on the corner, so there is only one line.'
          : 'The angle at the middle point (the corner) between the lines to the two outer points.',
      });
    } else if (shape.kind === 'zone') {
      const [a, b] = shape.points;
      const depth = Math.abs(b[0] - a[0]);
      const across = Math.abs(b[1] - a[1]);
      findings.push({
        title: nameOf(shape, shape.properties.zone_type || 'Space'),
        value: `${depth.toFixed(1)} × ${across.toFixed(1)} m`,
        detail: `${depth.toFixed(1)} m deep (towards goal) and ${across.toFixed(1)} m wide. You marked this space; `
          + 'the app did not detect it.',
      });
    }
  }
  return findings;
}

/**
 * The frame layer: only angles, and only as angles ON THE PICTURE.
 * `frame` is { width, height } in pixels. Stored frame points are fractions, and a
 * frame is not square, so they are turned into pixels first; measuring the
 * fractions directly would give the wrong angle.
 */
export function measureFrame(shapes, frame) {
  const findings = [];
  for (const shape of shapes) {
    if (shape.layer !== 'frame' || shape.kind !== 'angle') continue;
    const [first, corner, third] = shape.points.map(([x, y]) => [x * frame.width, y * frame.height]);
    const value = angleAt(corner, first, third);
    findings.push({
      title: nameOf(shape, 'Angle on the picture'),
      value: degrees(value),
      detail: value === null
        ? 'Undefined: one of the outer points sits exactly on the corner.'
        : 'Measured on the flat picture. The camera views the pitch at a slant, so this is NOT the real angle on '
          + 'the grass. Rebuild the situation on the pitch diagram for an estimate of that.',
    });
  }
  return findings;
}
