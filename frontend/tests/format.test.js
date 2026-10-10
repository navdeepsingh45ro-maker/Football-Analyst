// Clocks, dates and other text formatting.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { excerpt, formatClock, formatClockExact, formatDate, humanize, parseClock, plural } from '../js/format.js';

test('seconds are shown as a clock', () => {
  assert.equal(formatClock(0), '0:00');
  assert.equal(formatClock(59.9), '0:59');  // rounds down: never shows a second not yet reached
  assert.equal(formatClock(60), '1:00');
  assert.equal(formatClock(2110.4), '35:10');
  assert.equal(formatClock(3723), '1:02:03');
  assert.equal(formatClock(null), null);  // unknown stays unknown, it is not "0:00"
  assert.equal(formatClock(undefined), null);
  assert.equal(formatClock(NaN), null);
});

test('a clock is read back into seconds', () => {
  assert.equal(parseClock('35:10'), 2110);
  assert.equal(parseClock('1:02:03'), 3723);
  assert.equal(parseClock('10:12.5'), 612.5);
  assert.equal(parseClock('95'), 95);  // plain seconds are fine too
  assert.equal(parseClock(' 0:07 '), 7);
  assert.equal(parseClock(''), null);
  assert.equal(parseClock('   '), null);
  assert.equal(parseClock(null), null);
});

test('malformed clocks are refused with a readable message', () => {
  for (const bad of ['ab:cd', '12:75', '1:2:3:4', '-5', '-1:00', '12:', ':30', '1,5', '1:60:00']) {
    assert.throws(() => parseClock(bad), /clock like 32:14/, bad);
  }
});

test('an untouched timestamp in an edit form is saved back exactly', () => {
  // The edit form shows formatClockExact(stored) and saves parseClock(field).
  for (const stored of [0, 7, 59.999, 60, 612.5, 2110.4, 3723, 86399.25, 0.001]) {
    assert.equal(parseClock(formatClockExact(stored)), stored, String(stored));
  }
  assert.equal(formatClockExact(612.5), '10:12.5');
  assert.equal(formatClockExact(3723), '1:02:03');
  assert.equal(formatClockExact(null), '');
});

test('dates are shown without any timezone shifting the day', () => {
  assert.equal(formatDate('2026-03-08'), '8 Mar 2026');
  assert.equal(formatDate('2025-12-31'), '31 Dec 2025');
  assert.equal(formatDate('2026-01-01T00:00:00Z'), '1 Jan 2026');
  assert.equal(formatDate(null), null);
});

test('small helpers', () => {
  assert.equal(plural(1, 'observation'), '1 observation');
  assert.equal(plural(0, 'observation'), '0 observations');
  assert.equal(plural(2, 'match', 'matches'), '2 matches');
  assert.equal(humanize('first_touch'), 'First touch');
  assert.equal(excerpt('short'), 'short');
  assert.equal(excerpt('a'.repeat(200), 10).length, 10);
  assert.equal(excerpt(null), '');
});
