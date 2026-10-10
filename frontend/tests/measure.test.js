// The measurements panel: known positions in, known read-outs out.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { measureFrame, measurePitch } from '../js/editor/measure.js';

const PITCH = { length: 105, width: 68 };
const shape = (uid, layer, kind, points, extra = {}) => ({ uid, layer, kind, points, label: null, player_id: null, properties: {}, ...extra });
const find = (findings, start) => findings.find((finding) => finding.title.startsWith(start));

test('distances and angles from the studied player', () => {
  const findings = measurePitch([
    shape('s', 'pitch', 'subject', [[94, 34]], { label: '9' }),  // on the penalty spot
    shape('b', 'pitch', 'ball', [[83, 34]]),                     // 11 m behind
    shape('d1', 'pitch', 'defender', [[97, 38]], { label: 'CB' }),  // 3-4-5 triangle: 5 m away
    shape('d2', 'pitch', 'defender', [[94, 46]]),                // 12 m away
    shape('m', 'pitch', 'attacker', [[88, 26]], { label: '11' }),   // 6-8-10 triangle: 10 m away
  ], PITCH);

  const position = find(findings, 'Studied player 9: position');
  assert.equal(position.value, 'final third, central channel, opponent penalty area');
  assert.match(position.detail, /94\.0 m from own goal line, 11\.0 m from the goal line attacked/);

  assert.equal(find(findings, 'Studied player 9 to the ball').value, '11.0 m');
  assert.match(find(findings, 'Studied player 9 to the ball').detail, /back towards own goal/);

  const defenders = find(findings, 'Studied player 9 to defenders');
  assert.equal(defenders.value, 'nearest 5.0 m');
  assert.match(defenders.detail, /^defender CB: 5\.0 m.*defender: 12\.0 m/);  // nearest first

  assert.equal(find(findings, 'Studied player 9 to teammates').value, 'nearest 10.0 m');

  const goal = find(findings, 'Studied player 9 to the goal attacked');
  assert.equal(goal.value, '11.0 m');
  assert.match(goal.detail, /spans 36\.8°/);  // 2 * atan(3.66 / 11)
  assert.match(goal.detail, /not a passing angle/);

  // Ball straight behind, goal straight ahead: the two lines point in opposite directions.
  const opening = find(findings, 'Studied player 9: ball and goal');
  assert.equal(opening.value, '180.0°');
  assert.match(opening.detail, /does not know which way the player was facing/);
});

test('runs, passes, spaces and angles are described with what they measure', () => {
  const findings = measurePitch([
    shape('r', 'pitch', 'movement', [[78, 30.5], [92, 24]], { properties: { recorded_movement: true } }),
    shape('p', 'pitch', 'pass', [[60, 34], [72, 34]]),
    shape('z', 'pitch', 'zone', [[100, 30], [86, 14]], { properties: { zone_type: 'Half-space' } }),
    shape('a', 'pitch', 'angle', [[60, 30], [50, 30], [50, 45]], { label: 'cover' }),
  ], PITCH);

  const run = find(findings, 'Run');
  assert.equal(run.title, 'Run (the recorded movement)');
  assert.equal(run.value, '15.4 m');  // sqrt(14^2 + 6.5^2) = 15.435
  assert.match(run.detail, /forward and to the left \(-25° from straight at goal/);
  assert.match(run.detail, /From final third, central channel to final third, left half-space/);
  assert.match(run.detail, /direction of travel you drew, not where the player was facing/);

  assert.equal(find(findings, 'Pass').value, '12.0 m');
  assert.match(find(findings, 'Pass').detail, /towards the goal being attacked/);

  const space = find(findings, 'Half-space');
  assert.equal(space.value, '14.0 × 16.0 m');  // corners may be given in any order
  assert.match(space.detail, /You marked this space; the app did not detect it/);

  assert.equal(find(findings, 'Angle cover').value, '90.0°');
});

test('degenerate shapes are reported as undefined, never as NaN', () => {
  const findings = measurePitch([
    shape('a', 'pitch', 'angle', [[50, 30], [50, 30], [60, 40]]),      // first point on the corner
    shape('r', 'pitch', 'movement', [[40, 40], [40, 40]]),             // a run of no length
  ], PITCH);
  assert.equal(find(findings, 'Angle').value, 'undefined');
  assert.match(find(findings, 'Angle').detail, /only one line/);
  assert.equal(find(findings, 'Run').value, '0.0 m');
  assert.match(find(findings, 'Run').detail, /no direction/);
  for (const finding of findings) assert.doesNotMatch(finding.value + finding.detail, /NaN/);
});

test('with no studied player, a chosen marker can be measured from instead', () => {
  const shapes = [shape('d', 'pitch', 'defender', [[84, 27]], { label: 'CB' }), shape('b', 'pitch', 'ball', [[84, 30]])];
  assert.equal(measurePitch(shapes, PITCH).length, 0);
  const focused = measurePitch(shapes, PITCH, 'd');
  assert.equal(find(focused, 'defender CB to the ball').value, '3.0 m');
});

test('an angle on a video frame is measured in pixels and labelled as not real-world', () => {
  const frame = { width: 1280, height: 720 };
  const findings = measureFrame([
    // In PIXELS this is a right angle: 320 px to the right, and 180 px up.
    shape('a', 'frame', 'angle', [[0.75, 0.5], [0.5, 0.5], [0.5, 0.25]]),
    // As fractions this LOOKS like 45 degrees (0.1 across, 0.1 down). The frame is
    // not square: in pixels it is 128 across and 72 down, which is 29.4 degrees.
    shape('b', 'frame', 'angle', [[0.6, 0.5], [0.5, 0.5], [0.6, 0.6]]),
    shape('ignored', 'pitch', 'angle', [[10, 10], [20, 20], [30, 10]]),
    shape('also ignored', 'frame', 'movement', [[0.1, 0.1], [0.2, 0.2]]),
  ], frame);

  assert.equal(findings.length, 2);
  assert.equal(findings[0].value, '90.0°');
  const expected = (Math.atan2(72, 128) * 180) / Math.PI;
  assert.equal(findings[1].value, `${expected.toFixed(1)}°`);
  assert.equal(findings[1].value, '29.4°');
  assert.match(findings[0].detail, /NOT the real angle on the grass/);
});

test('the frame layer never reports a distance', () => {
  const findings = measureFrame([
    shape('m', 'frame', 'movement', [[0.1, 0.1], [0.9, 0.9]]),
    shape('s', 'frame', 'subject', [[0.5, 0.5]]),
    shape('b', 'frame', 'ball', [[0.6, 0.5]]),
  ], { width: 1280, height: 720 });
  assert.deepEqual(findings, []);
});
