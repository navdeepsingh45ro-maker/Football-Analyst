"""Acceptance test G: angle and distance calculations with known inputs and expected outputs,
including the degenerate cases (coincident points, zero-length vectors).

The examples live in test_fixtures/geometry_cases.json and are shared with the
JavaScript tests, so both implementations are held to the same answers.
"""
import json
import math
from pathlib import Path

import pytest

from services import geometry

CASES = json.loads((Path(__file__).resolve().parents[2] / "test_fixtures" / "geometry_cases.json").read_text())
TOLERANCE = CASES["tolerance"]


def _close(actual, expected) -> bool:
    """Equal within the tolerance. None must match None exactly; dicts are compared key by key."""
    if expected is None or actual is None:
        return actual is expected
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(_close(actual[key], expected[key]) for key in expected)
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return math.isclose(actual, expected, abs_tol=TOLERANCE)
    return actual == expected


def _label(case) -> str:
    return case.get("why") or json.dumps({k: v for k, v in case.items() if k != "expected"})


@pytest.mark.parametrize("case", CASES["distance"], ids=_label)
def test_distance(case):
    assert _close(geometry.distance(tuple(case["a"]), tuple(case["b"])), case["expected"])


@pytest.mark.parametrize("case", CASES["direction_degrees"], ids=_label)
def test_direction_degrees(case):
    assert _close(geometry.direction_degrees(tuple(case["start"]), tuple(case["end"])), case["expected"])


@pytest.mark.parametrize("case", CASES["describe_direction"], ids=_label)
def test_describe_direction(case):
    assert geometry.describe_direction(case["degrees"]) == case["expected"]


@pytest.mark.parametrize("case", CASES["angle_between"], ids=_label)
def test_angle_between(case):
    assert _close(geometry.angle_between(tuple(case["v1"]), tuple(case["v2"])), case["expected"])


@pytest.mark.parametrize("case", CASES["angle_at"], ids=_label)
def test_angle_at(case):
    actual = geometry.angle_at(tuple(case["vertex"]), tuple(case["a"]), tuple(case["b"]))
    assert _close(actual, case["expected"])


@pytest.mark.parametrize("case", CASES["goal_mouth_angle"], ids=_label)
def test_goal_mouth_angle(case):
    assert _close(geometry.goal_mouth_angle(tuple(case["position"]), *case["pitch"]), case["expected"])


@pytest.mark.parametrize("case", CASES["pitch_zone"], ids=_label)
def test_pitch_zone(case):
    assert geometry.pitch_zone(tuple(case["position"]), *case["pitch"]) == case["expected"]


@pytest.mark.parametrize("case", CASES["distances_to_boundaries"], ids=_label)
def test_distances_to_boundaries(case):
    assert _close(geometry.distances_to_boundaries(tuple(case["position"]), *case["pitch"]), case["expected"])


def test_degenerate_inputs_never_raise_or_return_nan():
    """Whatever the points, the answer is a real number or None. Never an exception, never NaN."""
    awkward = [(0.0, 0.0), (0.0, 0.0), (1e-15, -1e-15), (105.0, 34.0), (-5.0, 73.0), (1e9, -1e9)]
    for a in awkward:
        for b in awkward:
            assert math.isfinite(geometry.distance(a, b))
            for value in (geometry.direction_degrees(a, b), geometry.angle_between(a, b),
                          geometry.goal_mouth_angle(a)):
                assert value is None or math.isfinite(value)
            for c in awkward:
                value = geometry.angle_at(a, b, c)
                assert value is None or (0.0 <= value <= 180.0)


def test_nearly_parallel_vectors_do_not_break_acos():
    # Rounding can make the cosine come out as 1.0000000000000002; acos of that would be an error.
    assert geometry.angle_between((1.0, 1.0), (1.0000000000000002, 1.0)) == pytest.approx(0.0, abs=1e-6)
    assert geometry.angle_between((1e8, 1e-8), (1e8, 1e-8)) == pytest.approx(0.0, abs=1e-6)
