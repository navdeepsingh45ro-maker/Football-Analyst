// Acceptance test G (JavaScript half): the same worked examples the Python tests use.
// If geometry.js and geometry.py ever disagree, one of the two suites fails.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import * as geometry from '../js/editor/geometry.js';

const cases = JSON.parse(readFileSync(new URL('../../test_fixtures/geometry_cases.json', import.meta.url), 'utf8'));
const TOLERANCE = cases.tolerance;

function assertClose(actual, expected, label) {
  if (expected === null) {
    assert.equal(actual, null, label);
  } else if (typeof expected === 'number') {
    assert.equal(typeof actual, 'number', `${label}: expected a number, got ${actual}`);
    assert.ok(Math.abs(actual - expected) <= TOLERANCE, `${label}: got ${actual}, expected ${expected}`);
  } else if (typeof expected === 'object') {
    assert.deepEqual(Object.keys(actual).sort(), Object.keys(expected).sort(), label);
    for (const key of Object.keys(expected)) assertClose(actual[key], expected[key], `${label} › ${key}`);
  } else {
    assert.equal(actual, expected, label);
  }
}

const label = (example) => example.why || JSON.stringify({ ...example, expected: undefined });

test('distance', () => {
  for (const example of cases.distance) assertClose(geometry.distance(example.a, example.b), example.expected, label(example));
});

test('direction of travel, including a movement of no length', () => {
  for (const example of cases.direction_degrees) {
    assertClose(geometry.directionDegrees(example.start, example.end), example.expected, label(example));
  }
});

test('directions in words', () => {
  for (const example of cases.describe_direction) {
    assert.equal(geometry.describeDirection(example.degrees), example.expected, label(example));
  }
});

test('angle between two vectors, including zero-length vectors', () => {
  for (const example of cases.angle_between) {
    assertClose(geometry.angleBetween(example.v1, example.v2), example.expected, label(example));
  }
});

test('angle at a point, including coincident points', () => {
  for (const example of cases.angle_at) {
    assertClose(geometry.angleAt(example.vertex, example.a, example.b), example.expected, label(example));
  }
});

test('how wide the goal looks from a position', () => {
  for (const example of cases.goal_mouth_angle) {
    assertClose(geometry.goalMouthAngle(example.position, ...example.pitch), example.expected, label(example));
  }
});

test('thirds, lanes and penalty areas', () => {
  for (const example of cases.pitch_zone) {
    assert.deepEqual(geometry.pitchZone(example.position, ...example.pitch), example.expected, label(example));
  }
});

test('distances to the lines around the pitch', () => {
  for (const example of cases.distances_to_boundaries) {
    assertClose(geometry.distancesToBoundaries(example.position, ...example.pitch), example.expected, label(example));
  }
});

test('awkward inputs give a real number or null, never NaN and never an exception', () => {
  const awkward = [[0, 0], [1e-15, -1e-15], [105, 34], [-5, 73], [1e9, -1e9]];
  for (const a of awkward) {
    for (const b of awkward) {
      assert.ok(Number.isFinite(geometry.distance(a, b)));
      for (const value of [geometry.directionDegrees(a, b), geometry.angleBetween(a, b), geometry.goalMouthAngle(a)]) {
        assert.ok(value === null || Number.isFinite(value));
      }
      for (const c of awkward) {
        const value = geometry.angleAt(a, b, c);
        assert.ok(value === null || (value >= 0 && value <= 180));
      }
    }
  }
});

test('a straight run and a curved run are measured along their path', () => {
  assert.equal(geometry.pathLength([[0, 0], [3, 4]]), 5);
  // Bent through a point off the straight line: longer than the straight distance.
  const curved = geometry.pathLength([[0, 0], [10, 0], [5, 3]]);
  assert.ok(curved > 10 && curved < 13, `curved length ${curved}`);
  // "Bent" through the exact midpoint is not bent at all.
  assert.ok(Math.abs(geometry.pathLength([[0, 0], [10, 0], [5, 0]]) - 10) < 1e-9);
  // The curve really passes through the handle at its middle.
  const control = geometry.controlPoint([0, 0], [10, 0], [5, 3]);
  assert.deepEqual(geometry.curvePoint([0, 0], control, [10, 0], 0.5), [5, 3]);
});
