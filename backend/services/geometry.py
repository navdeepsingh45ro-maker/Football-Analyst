"""Pitch geometry: distances, directions and angles between positions you recorded.

THE COORDINATE SYSTEM (the same one the pitch diagram uses)
-----------------------------------------------------------
Positions are (x, y) in METRES on a pitch of pitch_length x pitch_width:

      y = 0  ───────────── left touchline (as the studied team attacks) ─────────────
             |                                                                      |
   own goal  |      the team you are studying attacks  ──────────────►             |  goal attacked
    x = 0    |                                                                      |  x = pitch_length
             |                                                                      |
      y = W  ───────────────────────────── right touchline ───────────────────────────

WHAT THESE NUMBERS ARE, AND ARE NOT
-----------------------------------
Every position was placed by eye on a diagram, so every result is an ESTIMATE.
The maths is exact; the inputs are not. Nothing here knows which way a player
was facing: a movement arrow gives a direction of travel, never body orientation.

This file has a twin, frontend/js/editor/geometry.js, used for the live read-outs
while you draw. Both are tested against the same list of worked examples
(test_fixtures/geometry_cases.json), so they cannot quietly drift apart.
"""
import math

Point = tuple[float, float]

EPSILON = 1e-9  # anything shorter than this has no direction

# Fixed by the laws of the game (metres).
GOAL_WIDTH = 7.32
PENALTY_AREA_DEPTH = 16.5
PENALTY_AREA_HALF_WIDTH = 20.16  # 40.32 wide, centred on the goal
GOAL_AREA_HALF_WIDTH = 9.16  # 18.32 wide, centred on the goal

LANES = ("left wide channel", "left half-space", "central channel", "right half-space", "right wide channel")
THIRDS = ("defensive third", "middle third", "final third")


def distance(a: Point, b: Point) -> float:
    """Straight-line distance between two positions, in metres."""
    return math.hypot(b[0] - a[0], b[1] - a[1])


def direction_degrees(start: Point, end: Point) -> float | None:
    """Direction of travel from `start` to `end`, relative to the direction of attack.

       0    straight towards the goal being attacked
     +90    straight towards the right touchline
     -90    straight towards the left touchline
     180    straight back towards the player's own goal

    None when the two points are the same (a movement of no length has no direction).
    """
    dx, dy = end[0] - start[0], end[1] - start[1]
    if math.hypot(dx, dy) < EPSILON:
        return None
    degrees = math.degrees(math.atan2(dy, dx))
    return 180.0 if degrees == -180.0 else degrees  # "straight back" is always +180, never -180


def describe_direction(degrees: float | None) -> str | None:
    """A direction in plain words. Describes geometry only; it does not name a type of run."""
    if degrees is None:
        return None
    side = "right" if degrees > 0 else "left"
    size = abs(degrees)
    if size < 22.5:
        return "towards the goal being attacked"
    if size < 67.5:
        return f"forward and to the {side}"
    if size < 112.5:
        return f"across the pitch to the {side}"
    if size < 157.5:
        return f"backward and to the {side}"
    return "back towards own goal"


def angle_between(v1: Point, v2: Point) -> float | None:
    """The angle between two vectors, 0 to 180 degrees. None if either has no length."""
    if math.hypot(*v1) < EPSILON or math.hypot(*v2) < EPSILON:
        return None
    dot = v1[0] * v2[0] + v1[1] * v2[1]  # how much the vectors point the same way
    cross = v1[0] * v2[1] - v1[1] * v2[0]  # how much they point across each other
    # atan2(|cross|, dot) rather than acos(dot / lengths): acos loses precision for
    # nearly parallel vectors and fails outright if rounding nudges its input past 1.
    return math.degrees(math.atan2(abs(cross), dot))


def angle_at(vertex: Point, a: Point, b: Point) -> float | None:
    """The angle at `vertex` between the line to `a` and the line to `b`.

    None when `a` or `b` sits exactly on the vertex, because then one of the two
    lines does not exist.
    """
    return angle_between((a[0] - vertex[0], a[1] - vertex[1]), (b[0] - vertex[0], b[1] - vertex[1]))


def goal_posts(pitch_length: float, pitch_width: float) -> tuple[Point, Point]:
    """The two posts of the goal being attacked."""
    centre = pitch_width / 2
    return (pitch_length, centre - GOAL_WIDTH / 2), (pitch_length, centre + GOAL_WIDTH / 2)


def goal_mouth_angle(position: Point, pitch_length: float = 105.0, pitch_width: float = 68.0) -> float | None:
    """How wide the goal being attacked looks from `position`: the angle between the two posts.

    A purely geometric quantity. It says nothing about the goalkeeper, defenders
    or the quality of a shot, and it is NOT a passing angle.
    """
    near_post, far_post = goal_posts(pitch_length, pitch_width)
    return angle_at(position, near_post, far_post)


def pitch_zone(position: Point, pitch_length: float = 105.0, pitch_width: float = 68.0) -> dict:
    """Which third and which lane a position is in.

    Thirds split the length into three equal parts. Lanes use one common
    convention: the edges of the penalty area and of the goal area, extended up
    the pitch, give five lanes (wide, half-space, centre, half-space, wide).
    Other analysts draw these lines elsewhere; this is the convention THIS app
    uses, applied the same way to every observation.
    """
    x, y = position
    if not (0 <= x <= pitch_length and 0 <= y <= pitch_width):
        return {"on_pitch": False, "third": None, "lane": None, "area": None}

    third = THIRDS[min(2, int(x // (pitch_length / 3)))]

    centre = pitch_width / 2
    edges = (centre - PENALTY_AREA_HALF_WIDTH, centre - GOAL_AREA_HALF_WIDTH,
             centre + GOAL_AREA_HALF_WIDTH, centre + PENALTY_AREA_HALF_WIDTH)
    lane = LANES[sum(1 for edge in edges if y >= edge)]

    in_box_width = abs(y - centre) <= PENALTY_AREA_HALF_WIDTH
    if in_box_width and x >= pitch_length - PENALTY_AREA_DEPTH:
        area = "opponent penalty area"
    elif in_box_width and x <= PENALTY_AREA_DEPTH:
        area = "own penalty area"
    else:
        area = None
    return {"on_pitch": True, "third": third, "lane": lane, "area": area}


def distances_to_boundaries(position: Point, pitch_length: float = 105.0, pitch_width: float = 68.0) -> dict:
    """How far a position is from each line around the pitch, in metres (negative = beyond it)."""
    x, y = position
    return {
        "own_goal_line": x,
        "opponent_goal_line": pitch_length - x,
        "left_touchline": y,
        "right_touchline": pitch_width - y,
    }
