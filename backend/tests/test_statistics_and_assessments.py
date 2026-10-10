"""Measured statistics versus subjective assessments, and the history of opinions."""
import pytest

from tests.helpers import create_assessment, create_match, create_player


# ── Statistics ───────────────────────────────────────────────────────────────
def _season_line(**overrides) -> dict:
    return {"scope": "season", "season": "2025/26", "competition": "Example League", "team": "Northside FC",
            "source": "Counted from video", **overrides}


def test_numbers_not_recorded_stay_unknown_instead_of_zero(client):
    player = create_player(client)
    response = client.post(f"/api/players/{player['id']}/statistics",
                           json=_season_line(appearances=12, minutes_played=940, goals=7, shots=""))
    assert response.status_code == 201, response.text
    line = response.json()
    assert (line["appearances"], line["minutes_played"], line["goals"]) == (12, 940, 7)
    assert line["shots"] is None  # blank = not recorded
    assert line["assists"] is None  # never supplied = not recorded, and NOT 0
    assert line["context"] == "2025/26, Example League, Northside FC"
    assert line["source"] == "Counted from video"


def test_a_match_line_takes_its_context_from_the_match(client):
    player = create_player(client)
    match = create_match(client)
    response = client.post(f"/api/players/{player['id']}/statistics",
                           json={"scope": "match", "match_id": match["id"], "minutes_played": 90, "shots": 4,
                                 "shots_on_target": 2, "extra_metrics": {"touches in box": 9},
                                 "source": "Counted from video"})
    assert response.status_code == 201, response.text
    line = response.json()
    assert line["context"] == "Northside FC v Riverton United (2026-03-08)"
    assert line["match"]["id"] == match["id"]
    assert line["extra_metrics"] == {"touches in box": 9.0}


def test_nothing_can_be_counted_twice(client):
    player = create_player(client)
    match = create_match(client)
    url = f"/api/players/{player['id']}/statistics"
    match_line = {"scope": "match", "match_id": match["id"], "goals": 1, "source": "Video"}

    assert client.post(url, json=match_line).status_code == 201
    assert client.post(url, json=match_line).status_code == 409  # second line for the same match

    assert client.post(url, json=_season_line(goals=7)).status_code == 201
    assert client.post(url, json=_season_line(goals=8)).status_code == 409  # same season + competition + team
    assert client.post(url, json=_season_line(goals=2, competition="Example Cup")).status_code == 201
    # "Unknown competition" is its own bucket and is also protected from doubles.
    assert client.post(url, json=_season_line(goals=1, competition=None, team=None)).status_code == 201
    assert client.post(url, json=_season_line(goals=1, competition=None, team=None)).status_code == 409


@pytest.mark.parametrize("bad", [
    {"scope": "season", "season": "2025/26", "goals": 3},  # no source
    {"scope": "season", "goals": 3, "source": "X"},  # no season
    {"scope": "match", "goals": 1, "source": "X"},  # no match
    {"scope": "season", "season": "2025/26", "source": "X"},  # no numbers at all
    {"scope": "season", "season": "2025/26", "goals": -1, "source": "X"},
    {"scope": "season", "season": "2025/26", "shots": 3, "shots_on_target": 5, "source": "X"},
    {"scope": "season", "season": "2025/26", "passes_completed": 30, "passes_attempted": 20, "source": "X"},
    {"scope": "season", "season": "2025/26", "goals": 1, "source": "X", "source_url": "ftp://example.com"},
    {"scope": "season", "season": "2025/26", "goals": 1, "source": "X", "extra_metrics": {"": 1}},
])
def test_invalid_stat_lines_are_rejected(client, bad):
    player = create_player(client)
    assert client.post(f"/api/players/{player['id']}/statistics", json=bad).status_code == 422
    assert client.get(f"/api/players/{player['id']}/statistics").json() == []


def test_match_line_specific_rules(client):
    player = create_player(client)
    match = create_match(client)
    url = f"/api/players/{player['id']}/statistics"
    base = {"scope": "match", "match_id": match["id"], "source": "Video"}
    assert client.post(url, json={**base, "minutes_played": 200}).status_code == 422
    assert client.post(url, json={**base, "appearances": 1}).status_code == 422
    assert client.post(url, json={**base, "goals": 1, "season": "2025/26"}).status_code == 422
    assert client.post(url, json={**base, "match_id": 999, "goals": 1}).status_code == 404


def test_editing_and_deleting_a_stat_line(client):
    player = create_player(client)
    url = f"/api/players/{player['id']}/statistics"
    line = client.post(url, json=_season_line(goals=7)).json()

    updated = client.put(f"/api/statistics/{line['id']}", json=_season_line(goals=9, assists=3))
    assert updated.status_code == 200
    assert (updated.json()["goals"], updated.json()["assists"]) == (9, 3)

    assert client.delete(f"/api/statistics/{line['id']}").status_code == 204
    assert client.get(url).json() == []


# ── Scouting assessments ─────────────────────────────────────────────────────
def test_an_assessment_holds_text_and_explicitly_scaled_ratings(client):
    player = create_player(client)
    assessment = create_assessment(
        client, player["id"], basis="Two fictional matches", weaknesses="Hold-up play under pressure.",
        ratings=[{"attribute": "finishing", "rating": 4, "note": "Calm one-on-one."},
                 {"attribute": "pressing", "rating": 2}],
    )
    assert assessment["weaknesses"] == "Hold-up play under pressure."
    assert {(r["attribute"], r["rating"]) for r in assessment["ratings"]} == {("finishing", 4), ("pressing", 2)}
    # The scale itself is published, so a number is never shown without its meaning.
    vocabulary = client.get("/api/meta/vocabulary").json()
    assert vocabulary["rating_scale"] == {"1": "Clear weakness", "2": "Below the level",
                                          "3": "Adequate for the level", "4": "A strength", "5": "Outstanding"}
    assert "subjective" in vocabulary["rating_scale_note"]


@pytest.mark.parametrize("bad", [
    {},  # nothing in it
    {"summary": "x", "assessed_on": "2999-01-01"},
    {"ratings": [{"attribute": "finishing", "rating": 6}]},
    {"ratings": [{"attribute": "finishing", "rating": 0}]},
    {"ratings": [{"attribute": "charisma", "rating": 3}]},
    {"ratings": [{"attribute": "finishing", "rating": 3}, {"attribute": "finishing", "rating": 4}]},
])
def test_invalid_assessments_are_rejected(client, bad):
    player = create_player(client)
    assert client.post(f"/api/players/{player['id']}/assessments", json=bad).status_code == 422
    assert client.get(f"/api/players/{player['id']}/assessments").json() == []


def test_a_new_assessment_never_overwrites_an_older_one(client):
    """What I believed months ago stays available next to what I believe now."""
    player = create_player(client)
    spring = create_assessment(client, player["id"], assessed_on="2026-03-01", summary="Raw but quick.",
                               ratings=[{"attribute": "finishing", "rating": 2},
                                        {"attribute": "off_ball_movement", "rating": 3}])
    autumn = create_assessment(client, player["id"], assessed_on="2026-09-15", summary="Much calmer in the box.",
                               ratings=[{"attribute": "finishing", "rating": 4}])

    listed = client.get(f"/api/players/{player['id']}/assessments").json()
    assert [a["id"] for a in listed] == [autumn["id"], spring["id"]]  # newest first
    assert listed[1]["summary"] == "Raw but quick."  # the old opinion is untouched
    assert {(r["attribute"], r["rating"]) for r in listed[1]["ratings"]} == {("finishing", 2),
                                                                             ("off_ball_movement", 3)}

    history = client.get(f"/api/players/{player['id']}/rating-history").json()
    assert history["assessment_count"] == 2
    trends = {trend["attribute"]: trend for trend in history["trends"]}
    finishing = trends["finishing"]
    assert [point["rating"] for point in finishing["points"]] == [2, 4]  # oldest first
    assert (finishing["first_rating"], finishing["latest_rating"], finishing["change"]) == (2, 4, 2)
    movement = trends["off_ball_movement"]
    assert [point["rating"] for point in movement["points"]] == [3, None]  # not rated the second time
    assert movement["change"] is None  # one rating is not a trend
    assert trends["passing"]["latest_rating"] is None  # never rated


def test_correcting_an_assessment_replaces_its_ratings(client):
    player = create_player(client)
    assessment = create_assessment(client, player["id"], ratings=[{"attribute": "finishing", "rating": 2},
                                                                  {"attribute": "passing", "rating": 3}])
    # Re-rating the same attribute must not trip the one-rating-per-attribute rule.
    response = client.put(f"/api/assessments/{assessment['id']}",
                          json={"assessed_on": "2026-03-01", "summary": "Corrected.",
                                "ratings": [{"attribute": "finishing", "rating": 3}]})
    assert response.status_code == 200, response.text
    assert [(r["attribute"], r["rating"]) for r in response.json()["ratings"]] == [("finishing", 3)]
    assert len(client.get(f"/api/players/{player['id']}/assessments").json()) == 1  # edited in place, no copy


def test_changing_the_biography_leaves_assessments_alone(client):
    """Acceptance test H, first half (observations are covered in test_observations.py)."""
    player = create_player(client, full_name="Alex Example", current_team="Northside FC", shirt_number=9)
    assessment = create_assessment(client, player["id"], summary="Sharp movement in the box.")

    client.put(f"/api/players/{player['id']}",
               json={"full_name": "Alexander Example", "current_team": "Riverton United", "shirt_number": 19})

    after = client.get(f"/api/players/{player['id']}/assessments").json()
    assert [(a["id"], a["summary"], a["assessed_on"]) for a in after] == [
        (assessment["id"], "Sharp movement in the box.", "2026-03-01")]
    assert client.get(f"/api/players/{player['id']}").json()["full_name"] == "Alexander Example"
