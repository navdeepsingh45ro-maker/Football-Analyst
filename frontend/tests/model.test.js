// The diagram's data model: adding, changing, undo and redo.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { AnnotationDocument, KINDS, newUid } from '../js/editor/model.js';

const defender = (x = 84, y = 27) => ({ layer: 'pitch', kind: 'defender', points: [[x, y]] });
const run = (layer = 'pitch') => ({ layer, kind: 'movement', points: [[78, 30.5], [92, 24]] });

test('uids are unique and fit the format the API accepts', () => {
  const uids = new Set(Array.from({ length: 500 }, newUid));
  assert.equal(uids.size, 500);
  for (const uid of uids) assert.match(uid, /^[A-Za-z0-9_-]{1,40}$/);
});

test('the kinds match what the backend accepts', () => {
  assert.deepEqual(Object.keys(KINDS).sort(),
    ['angle', 'attacker', 'ball', 'defender', 'goalkeeper', 'line', 'movement', 'pass', 'subject', 'text', 'zone']);
});

test('add, undo, redo', () => {
  const diagram = new AnnotationDocument();
  assert.equal(diagram.canUndo, false);
  const uid = diagram.add(defender());
  assert.equal(diagram.shapes.length, 1);
  assert.deepEqual(diagram.find(uid), { uid, layer: 'pitch', kind: 'defender', points: [[84, 27]],
    label: null, player_id: null, properties: {} });

  diagram.undo();
  assert.equal(diagram.shapes.length, 0);
  assert.equal(diagram.canRedo, true);

  diagram.redo();
  assert.equal(diagram.find(uid).points[0][0], 84);
  assert.equal(diagram.canRedo, false);
});

test('a new change after undo discards what could have been redone', () => {
  const diagram = new AnnotationDocument();
  diagram.add(defender(10, 10));
  diagram.add(defender(20, 20));
  diagram.undo();
  diagram.add(defender(30, 30));
  assert.equal(diagram.canRedo, false);
  assert.deepEqual(diagram.shapes.map((shape) => shape.points[0][0]), [10, 30]);
});

test('a whole drag is one undo step', () => {
  const diagram = new AnnotationDocument();
  const uid = diagram.add(defender(50, 30));
  diagram.beginGesture();
  for (let step = 0; step < 25; step += 1) diagram.moveBy(uid, 1, 0.5);
  diagram.endGesture();
  assert.deepEqual(diagram.find(uid).points, [[75, 42.5]]);

  diagram.undo();  // back to before the drag, not one pixel back
  assert.deepEqual(diagram.find(uid).points, [[50, 30]]);
  diagram.redo();
  assert.deepEqual(diagram.find(uid).points, [[75, 42.5]]);
});

test('a click that moves nothing leaves no undo step', () => {
  const diagram = new AnnotationDocument();
  diagram.add(defender());
  diagram.beginGesture();
  diagram.endGesture();
  diagram.undo();
  assert.equal(diagram.shapes.length, 0);  // the only step was "add"
});

test('moving keeps points inside the surface when a tidy function is given', () => {
  const diagram = new AnnotationDocument();
  const uid = diagram.add(defender(100, 60));
  diagram.moveBy(uid, 50, 50, ([x, y]) => [Math.min(x, 109), Math.min(y, 72)]);
  assert.deepEqual(diagram.find(uid).points, [[109, 72]]);
});

test('update changes fields and merges properties; empty values remove a property', () => {
  const diagram = new AnnotationDocument();
  const uid = diagram.add({ layer: 'pitch', kind: 'zone', points: [[80, 10], [100, 30]] });
  diagram.update(uid, { label: 'Space behind', properties: { zone_type: 'Half-space' } });
  assert.equal(diagram.find(uid).label, 'Space behind');
  assert.deepEqual(diagram.find(uid).properties, { zone_type: 'Half-space' });
  diagram.update(uid, { properties: { zone_type: '' } });
  assert.deepEqual(diagram.find(uid).properties, {});
  diagram.undo();
  assert.deepEqual(diagram.find(uid).properties, { zone_type: 'Half-space' });
});

test('the first run on the pitch is the recorded movement, and only one run can be', () => {
  const diagram = new AnnotationDocument();
  const onFrame = diagram.add(run('frame'));
  assert.equal(diagram.find(onFrame).properties.recorded_movement, undefined);  // frame arrows never are
  assert.equal(diagram.recordedMovement(), null);

  const first = diagram.add(run());
  const second = diagram.add(run());
  assert.equal(diagram.recordedMovement().uid, first);
  assert.equal(diagram.find(second).properties.recorded_movement, undefined);

  diagram.markRecordedMovement(second);
  assert.equal(diagram.recordedMovement().uid, second);
  assert.equal(diagram.find(first).properties.recorded_movement, undefined);
  assert.equal(diagram.shapes.filter((shape) => shape.properties.recorded_movement).length, 1);

  diagram.markRecordedMovement(null);
  assert.equal(diagram.recordedMovement(), null);
});

test('a run can be bent and straightened', () => {
  const diagram = new AnnotationDocument();
  const uid = diagram.add(run());
  diagram.setPoint(uid, 2, [86, 22]);
  assert.equal(diagram.find(uid).points.length, 3);
  diagram.straighten(uid);
  assert.deepEqual(diagram.find(uid).points, [[78, 30.5], [92, 24]]);
});

test('remove and clear, per layer and everything', () => {
  const diagram = new AnnotationDocument();
  const a = diagram.add(defender());
  diagram.add({ layer: 'frame', kind: 'ball', points: [[0.5, 0.5]] });
  diagram.add({ layer: 'frame', kind: 'defender', points: [[0.6, 0.4]] });
  assert.equal(diagram.onLayer('frame').length, 2);

  diagram.clear('frame');
  assert.deepEqual(diagram.shapes.map((shape) => shape.uid), [a]);
  diagram.undo();
  assert.equal(diagram.shapes.length, 3);

  diagram.remove(a);
  assert.equal(diagram.find(a), null);
  diagram.clear();
  assert.equal(diagram.shapes.length, 0);
  diagram.undo();
  diagram.undo();
  assert.equal(diagram.shapes.length, 3);
});

test('listeners are told about every change and can unsubscribe', () => {
  const diagram = new AnnotationDocument();
  let calls = 0;
  const stop = diagram.onChange(() => { calls += 1; });
  const uid = diagram.add(defender());
  diagram.update(uid, { label: 'CB' });
  diagram.undo();
  assert.equal(calls, 3);
  stop();
  diagram.redo();
  assert.equal(calls, 3);
});

test('a diagram opened from the API can be saved straight back', () => {
  // The API returns each shape with extras such as z_index, and refuses unknown
  // fields on save. Whatever goes in, only the editor's own fields come out.
  const fromApi = [
    { uid: 'ball-1', layer: 'pitch', kind: 'ball', points: [[60, 30]], label: null, player_id: null, properties: {}, z_index: 0 },
    { uid: 'run-1', layer: 'pitch', kind: 'movement', points: [[78, 30.5], [92, 24]], label: 'run', player_id: 7,
      properties: { recorded_movement: true }, z_index: 1, id: 99 },
  ];
  const allowed = ['kind', 'label', 'layer', 'player_id', 'points', 'properties', 'uid'];
  for (const diagram of [new AnnotationDocument(fromApi), (() => { const d = new AnnotationDocument(); d.load(fromApi); return d; })()]) {
    const saved = diagram.toJSON();
    for (const shape of saved) assert.deepEqual(Object.keys(shape).sort(), allowed);
    assert.deepEqual(saved.map((shape) => [shape.uid, shape.points, shape.label, shape.player_id]),
      [['ball-1', [[60, 30]], null, null], ['run-1', [[78, 30.5], [92, 24]], 'run', 7]]);
    assert.deepEqual(saved[1].properties, { recorded_movement: true });
  }
  // The copy is independent of what was passed in.
  const diagram = new AnnotationDocument(fromApi);
  fromApi[0].points[0][0] = 999;
  assert.equal(diagram.find('ball-1').points[0][0], 60);
});

test('what is saved is a copy in drawing order, and loading resets history', () => {
  const diagram = new AnnotationDocument();
  diagram.add(defender(10, 10));
  diagram.add(defender(20, 20));
  const saved = diagram.toJSON();
  saved[0].points[0][0] = 999;  // changing the saved copy must not change the diagram
  assert.equal(diagram.shapes[0].points[0][0], 10);
  assert.deepEqual(saved.map((shape) => shape.points[0][1]), [10, 20]);

  const reopened = new AnnotationDocument();
  reopened.load(diagram.toJSON());
  assert.deepEqual(reopened.toJSON(), diagram.toJSON());  // save -> load -> save is lossless
  assert.equal(reopened.canUndo, false);
});
