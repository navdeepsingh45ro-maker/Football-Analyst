// Pitch geometry: distances, directions and angles between positions you placed.
//
// This is the twin of backend/services/geometry.py. It exists in JavaScript too
// because the editor shows measurements live while you drag, which cannot wait
// for a round trip to the server. Both files are tested against the SAME worked
// examples (test_fixtures/geometry_cases.json), so they cannot drift apart.
//
// COORDINATES: [x, y] in metres. x = 0 is the goal line of the team you are
// studying and x = pitch length is the goal line they attack. y = 0 is the
// touchline on their left as they attack. See geometry.py for the full picture.
//
// Every result is an ESTIMATE, because the positions were placed by eye. And a
// movement arrow gives a direction of travel, never which way a player faced.

export const EPSILON = 1e-9;  // anything shorter than this has no direction

// Fixed by the laws of the game (metres).
export const GOAL_WIDTH = 7.32;
export const PENALTY_AREA_DEPTH = 16.5;
export const PENALTY_AREA_HALF_WIDTH = 20.16;
export const GOAL_AREA_DEPTH = 5.5;
export const GOAL_AREA_HALF_WIDTH = 9.16;
export const PENALTY_SPOT_DISTANCE = 11;
export const CENTRE_CIRCLE_RADIUS = 9.15;

export const LANES = ['left wide channel', 'left half-space', 'central channel', 'right half-space', 'right wide channel'];
export const THIRDS = ['defensive third', 'middle third', 'final third'];

const toDegrees = (radians) => (radians * 180) / Math.PI;

/** Straight-line distance between two positions. */
export function distance(a, b) {
  return Math.hypot(b[0] - a[0], b[1] - a[1]);
}

/**
 * Direction of travel from `start` to `end`, relative to the direction of attack:
 *    0 = straight towards the goal being attacked,  +90 = towards the right touchline,
 *  -90 = towards the left touchline,                180 = straight back towards own goal.
 * null when the two points are the same.
 */
export function directionDegrees(start, end) {
  const dx = end[0] - start[0];
  const dy = end[1] - start[1];
  if (Math.hypot(dx, dy) < EPSILON) return null;
  const degrees = toDegrees(Math.atan2(dy, dx));
  return degrees === -180 ? 180 : degrees;  // "straight back" is always +180, never -180
}

/** A direction in plain words. Describes geometry only; it does not name a type of run. */
export function describeDirection(degrees) {
  if (degrees === null || degrees === undefined) return null;
  const side = degrees > 0 ? 'right' : 'left';
  const size = Math.abs(degrees);
  if (size < 22.5) return 'towards the goal being attacked';
  if (size < 67.5) return `forward and to the ${side}`;
  if (size < 112.5) return `across the pitch to the ${side}`;
  if (size < 157.5) return `backward and to the ${side}`;
  return 'back towards own goal';
}

/** The angle between two vectors, 0 to 180 degrees. null if either has no length. */
export function angleBetween(v1, v2) {
  if (Math.hypot(v1[0], v1[1]) < EPSILON || Math.hypot(v2[0], v2[1]) < EPSILON) return null;
  const dot = v1[0] * v2[0] + v1[1] * v2[1];    // how much the vectors point the same way
  const cross = v1[0] * v2[1] - v1[1] * v2[0];  // how much they point across each other
  // atan2(|cross|, dot) rather than acos: accurate for nearly parallel vectors too.
  return toDegrees(Math.atan2(Math.abs(cross), dot));
}

/**
 * The angle at `vertex` between the line to `a` and the line to `b`.
 * null when `a` or `b` sits exactly on the vertex (one of the lines does not exist).
 */
export function angleAt(vertex, a, b) {
  return angleBetween([a[0] - vertex[0], a[1] - vertex[1]], [b[0] - vertex[0], b[1] - vertex[1]]);
}

/** The two posts of the goal being attacked. */
export function goalPosts(pitchLength = 105, pitchWidth = 68) {
  const centre = pitchWidth / 2;
  return [[pitchLength, centre - GOAL_WIDTH / 2], [pitchLength, centre + GOAL_WIDTH / 2]];
}

/**
 * How wide the goal being attacked looks from `position`: the angle between the posts.
 * Geometry only. It says nothing about the keeper or defenders, and it is NOT a passing angle.
 */
export function goalMouthAngle(position, pitchLength = 105, pitchWidth = 68) {
  const [nearPost, farPost] = goalPosts(pitchLength, pitchWidth);
  return angleAt(position, nearPost, farPost);
}

/**
 * Which third and which lane a position is in. Thirds split the length equally.
 * Lanes follow one common convention: the edges of the penalty area and of the
 * goal area, extended up the pitch. Other analysts draw them elsewhere; this is
 * the convention this app applies to every observation.
 */
export function pitchZone(position, pitchLength = 105, pitchWidth = 68) {
  const [x, y] = position;
  if (!(x >= 0 && x <= pitchLength && y >= 0 && y <= pitchWidth)) {
    return { on_pitch: false, third: null, lane: null, area: null };
  }
  const third = THIRDS[Math.min(2, Math.floor(x / (pitchLength / 3)))];

  const centre = pitchWidth / 2;
  const edges = [centre - PENALTY_AREA_HALF_WIDTH, centre - GOAL_AREA_HALF_WIDTH,
    centre + GOAL_AREA_HALF_WIDTH, centre + PENALTY_AREA_HALF_WIDTH];
  const lane = LANES[edges.filter((edge) => y >= edge).length];

  const inBoxWidth = Math.abs(y - centre) <= PENALTY_AREA_HALF_WIDTH;
  let area = null;
  if (inBoxWidth && x >= pitchLength - PENALTY_AREA_DEPTH) area = 'opponent penalty area';
  else if (inBoxWidth && x <= PENALTY_AREA_DEPTH) area = 'own penalty area';
  return { on_pitch: true, third, lane, area };
}

/** How far a position is from each line around the pitch, in metres (negative = beyond it). */
export function distancesToBoundaries(position, pitchLength = 105, pitchWidth = 68) {
  const [x, y] = position;
  return {
    own_goal_line: x,
    opponent_goal_line: pitchLength - x,
    left_touchline: y,
    right_touchline: pitchWidth - y,
  };
}

// ── Curved runs ──────────────────────────────────────────────────────────────
// A run is stored as [start, end] or, when curved, [start, end, through], where
// `through` is the point the run passes through at its middle (the handle you
// drag). It is drawn as a quadratic Bézier curve.

/** The Bézier control point that makes the curve pass through `through` at its middle. */
export function controlPoint(start, end, through) {
  return [2 * through[0] - (start[0] + end[0]) / 2, 2 * through[1] - (start[1] + end[1]) / 2];
}

/** A point on the curve from `start` to `end` with the given control point; t runs 0 to 1. */
export function curvePoint(start, control, end, t) {
  const u = 1 - t;
  return [u * u * start[0] + 2 * u * t * control[0] + t * t * end[0],
    u * u * start[1] + 2 * u * t * control[1] + t * t * end[1]];
}

/**
 * Length of a run along its path. A curve is measured by adding up 48 short
 * straight pieces, accurate to well under a centimetre for anything on a pitch.
 */
export function pathLength(points) {
  const [start, end, through] = points;
  if (!through) return distance(start, end);
  const control = controlPoint(start, end, through);
  let total = 0;
  let previous = start;
  for (let step = 1; step <= 48; step += 1) {
    const next = curvePoint(start, control, end, step / 48);
    total += distance(previous, next);
    previous = next;
  }
  return total;
}
