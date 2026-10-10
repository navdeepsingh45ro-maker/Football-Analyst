"""Acceptance test I: summary calculations return the expected records, and every
number can be traced back to the observations it counts."""
import pytest

from tests.helpers import add_to_lineup, create_match, create_observation, create_player, shape


def _run(start, end) -> dict:
    """A pitch diagram holding just the recorded movement."""
    return {"annotations": [shape("run", "pitch", "movement", [start, end], properties={"recorded_movement": True})]}


@pytest.fixture
def season(client):
    """A striker observed across three matches against two opponents, plus a centre-back."""
    striker = create_player(client, full_name="Sam Finisher", primary_position="ST", current_team="Northside FC")
    stopper = create_player(client, full_name="Pat Stopper", primary_position="CB", current_team="Riverton United")
    home = create_match(client, home_team="Northside FC", away_team="Riverton United", match_date="2025-11-02",
                        competition="Example League", season="2025/26")
    away = create_match(client, home_team="Riverton United", away_team="Northside FC", match_date="2026-02-14",
                        competition="Example League", season="2025/26")
    cup = create_match(client, home_team="Northside FC", away_team="Harbour City", match_date="2026-03-08",
                       competition="Example Cup", season="2025/26")
    for match in (home, cup):
        add_to_lineup(client, match["id"], striker["id"], side="home")
    add_to_lineup(client, away["id"], striker["id"], side="away")
    add_to_lineup(client, home["id"], stopper["id"], side="away")

    def observe(player, match, **fields):
        return create_observation(client, [player["id"]], match_id=match["id"], **fields)["id"]

    ids = {
        # Diagonal runs: three, in two matches, with different endings.
        "d1": observe(striker, home, movement_category="Diagonal run", outcome="Shot", defensive_shape="4-4-2",
                      snapshot=_run([78, 30.5], [92, 24])),      # final third central -> final third left half-space
        "d2": observe(striker, home, movement_category="Diagonal run", outcome="Not found by the pass",
                      snapshot=_run([60, 40], [80, 50])),        # middle third central -> final third right half-space
        "d3": observe(striker, cup, movement_category="Diagonal run", outcome="Goal",
                      snapshot=_run([75, 30], [95, 18])),        # final third central -> final third left half-space
        # Other movements.
        "c1": observe(striker, away, movement_category="Channel run", outcome="Chance created"),
        "k1": observe(striker, cup, movement_category="Checking towards the ball", outcome="Retained possession"),
        # No movement recorded at all.
        "f1": observe(striker, cup, category="Finishing", outcome="Goal"),
        # Another player.
        "s1": observe(stopper, home, category="Defensive positioning", outcome="Won the ball"),
    }
    return {"striker": striker, "stopper": stopper, "home": home, "away": away, "cup": cup, "ids": ids}


def _groups(body) -> dict:
    return {group["label"]: group for group in body["groups"]}


def test_movements_are_counted_and_each_count_lists_its_observations(client, season):
    ids = season["ids"]
    body = client.get("/api/analytics/patterns", params={"player_id": season["striker"]["id"],
                                                         "group_by": "movement_category"}).json()
    assert body["total"] == 6  # the striker's six observations; the centre-back's is filtered out
    groups = _groups(body)
    assert [(g["label"], g["count"]) for g in body["groups"]] == [
        ("Diagonal run", 3), ("Channel run", 1), ("Checking towards the ball", 1), ("Not recorded", 1)]
    assert sorted(groups["Diagonal run"]["observation_ids"]) == sorted([ids["d1"], ids["d2"], ids["d3"]])
    assert groups["Diagonal run"]["share"] == pytest.approx(0.5)
    assert groups["Diagonal run"]["matches"] == 2  # recorded in two different matches
    assert groups["Diagonal run"]["small_sample"] is True  # three is still a small number
    # "Not recorded" is its own group, last, and is not folded into anything else.
    assert groups["Not recorded"]["recorded"] is False
    assert groups["Not recorded"]["observation_ids"] == [ids["f1"]]
    assert sum(group["count"] for group in body["groups"]) == body["total"]


def test_a_reported_number_opens_as_exactly_those_records(client, season):
    """If the report says 3, the user can list the 3: by the group's filter, or by its ids."""
    base = {"player_id": season["striker"]["id"]}
    for dimension in client.get("/api/analytics/dimensions").json():
        body = client.get("/api/analytics/patterns", params={**base, "group_by": dimension}).json()
        for group in body["groups"]:
            expected = sorted(group["observation_ids"])
            by_ids = client.get("/api/observations", params={"ids": ",".join(map(str, expected))}).json()
            assert sorted(item["id"] for item in by_ids["items"]) == expected, (dimension, group["label"])
            assert by_ids["total"] == group["count"]
            if group["filter"]:
                by_filter = client.get("/api/observations", params={**base, **group["filter"]}).json()
                assert sorted(item["id"] for item in by_filter["items"]) == expected, (dimension, group["label"])


def test_observations_are_compared_across_matches_opponents_and_competitions(client, season):
    ids, striker = season["ids"], {"player_id": season["striker"]["id"]}

    by_match = _groups(client.get("/api/analytics/patterns", params={**striker, "group_by": "match"}).json())
    assert {label: group["count"] for label, group in by_match.items()} == {
        "Northside FC v Harbour City (2026-03-08)": 3,
        "Northside FC v Riverton United (2025-11-02)": 2,
        "Riverton United v Northside FC (2026-02-14)": 1,
    }

    # The opponent is worked out from the lineup: home in one match, away in the other.
    by_opponent = _groups(client.get("/api/analytics/patterns", params={**striker, "group_by": "opponent"}).json())
    assert {label: sorted(group["observation_ids"]) for label, group in by_opponent.items()} == {
        "Riverton United": sorted([ids["d1"], ids["d2"], ids["c1"]]),
        "Harbour City": sorted([ids["d3"], ids["k1"], ids["f1"]]),
    }

    by_competition = _groups(client.get("/api/analytics/patterns",
                                        params={**striker, "group_by": "competition"}).json())
    assert {label: group["count"] for label, group in by_competition.items()} == {"Example League": 3,
                                                                                 "Example Cup": 3}
    # Narrowing the filters narrows the report in the same way as the observation list.
    diagonal_runs = client.get("/api/analytics/patterns", params={
        **striker, "movement_category": "Diagonal run", "group_by": "opponent"}).json()
    assert {g["label"]: g["count"] for g in diagonal_runs["groups"]} == {"Riverton United": 2, "Harbour City": 1}


def test_opponent_is_reported_as_unknown_rather_than_guessed(client):
    drifter = create_player(client, full_name="Free Agent")  # no club, and in no lineup
    match = create_match(client)
    create_observation(client, [drifter["id"]], match_id=match["id"])
    create_observation(client, [drifter["id"]])  # no match at all
    body = client.get("/api/analytics/patterns", params={"group_by": "opponent"}).json()
    # Each reason for not knowing is reported separately, with its own count.
    assert {group["label"]: group["count"] for group in body["groups"]} == {
        "Opponent not known (no match or no player)": 1,
        "Opponent not known (the player is not in the match lineup)": 1,
    }
    assert all(group["recorded"] is False for group in body["groups"])
    assert body["total"] == 2
    assert any("2 of 2 observations have nothing recorded for this" in note for note in body["limitations"])


def test_movements_before_shots_and_chances(client, season):
    ids = season["ids"]
    body = client.get("/api/analytics/crosstab", params={
        "player_id": season["striker"]["id"], "rows": "movement_category", "columns": "outcome"}).json()
    table = {(row, column): body["cells"][r][c]
             for r, row in enumerate(body["row_labels"]) for c, column in enumerate(body["column_labels"])}
    assert table[("Diagonal run", "Shot")]["observation_ids"] == [ids["d1"]]
    assert table[("Diagonal run", "Goal")]["observation_ids"] == [ids["d3"]]
    assert table[("Diagonal run", "Not found by the pass")]["count"] == 1
    assert table[("Channel run", "Shot")] == {"count": 0, "observation_ids": []}
    assert table[("Not recorded", "Goal")]["observation_ids"] == [ids["f1"]]
    assert sum(body["row_totals"]) == sum(body["column_totals"]) == body["total"] == 6
    # The wording never claims the movement caused the outcome.
    assert any("does not show that one caused the other" in note for note in body["limitations"])

    # The same question through the filter: situations that ended in a shot or chance.
    ended_well = client.get("/api/analytics/patterns", params={
        "player_id": season["striker"]["id"], "ended_in_shot_or_chance": True, "group_by": "movement_category"}).json()
    assert {g["label"]: g["count"] for g in ended_well["groups"]} == {"Diagonal run": 2, "Channel run": 1,
                                                                      "Not recorded": 1}
    assert client.get("/api/analytics/crosstab", params={"rows": "outcome", "columns": "outcome"}).status_code == 422


def test_movements_are_grouped_by_pitch_zone_from_the_diagrams(client, season):
    ids, striker = season["ids"], {"player_id": season["striker"]["id"]}

    starts = _groups(client.get("/api/analytics/patterns", params={**striker, "group_by": "zone_start"}).json())
    assert sorted(starts["Final third, central channel"]["observation_ids"]) == sorted([ids["d1"], ids["d3"]])
    assert starts["Middle third, central channel"]["observation_ids"] == [ids["d2"]]
    assert starts["No recorded movement on a pitch diagram"]["count"] == 3  # honest about what cannot be placed

    ends = _groups(client.get("/api/analytics/patterns", params={**striker, "group_by": "zone_end"}).json())
    assert sorted(ends["Final third, left half-space"]["observation_ids"]) == sorted([ids["d1"], ids["d3"]])
    assert ends["Final third, right half-space"]["observation_ids"] == [ids["d2"]]

    directions = _groups(client.get("/api/analytics/patterns", params={**striker, "group_by": "direction"}).json())
    assert sorted(directions["Forward and to the left"]["observation_ids"]) == sorted([ids["d1"], ids["d3"]])
    assert directions["Forward and to the right"]["observation_ids"] == [ids["d2"]]

    grid = client.get("/api/analytics/zones", params={**striker, "point": "end"}).json()
    assert grid["thirds"] == ["defensive third", "middle third", "final third"]
    assert grid["lanes"][1] == "left half-space"
    final_third = grid["thirds"].index("final third")
    assert sorted(grid["cells"][grid["lanes"].index("left half-space")][final_third]["observation_ids"]) == sorted(
        [ids["d1"], ids["d3"]])
    assert grid["cells"][grid["lanes"].index("right half-space")][final_third]["observation_ids"] == [ids["d2"]]
    assert (grid["placed"], grid["without_position"]["count"], grid["total"]) == (3, 3, 6)
    assert any("3 of 6 matching observations have a recorded movement" in note for note in grid["limitations"])
    assert client.get("/api/analytics/zones", params={"point": "middle"}).status_code == 422


def test_small_samples_are_called_small(client, season):
    lonely = client.get("/api/analytics/patterns", params={"player_id": season["stopper"]["id"]}).json()
    assert lonely["total"] == 1
    notes = " ".join(lonely["limitations"])
    assert "counts of what you chose to record" in notes
    assert "Only 1 observation match" in notes and "far too few to call anything a pattern" in notes
    assert "They come from 1 match" in notes

    nothing = client.get("/api/analytics/patterns", params={"q": "no such text anywhere"}).json()
    assert nothing["total"] == 0 and nothing["groups"] == []
    assert any("nothing to count" in note for note in nothing["limitations"])
    assert client.get("/api/analytics/patterns", params={"group_by": "star_sign"}).status_code == 422
    assert client.get("/api/observations", params={"ids": "1,two"}).status_code == 422


# ── Comparing players ────────────────────────────────────────────────────────
def _stat_line(client, player, **numbers):
    body = {"scope": "season", "season": "2025/26", "competition": "Example League", "source": "Counted from video",
            **numbers}
    assert client.post(f"/api/players/{player['id']}/statistics", json=body).status_code == 201


def test_players_are_compared_without_treating_missing_numbers_as_zero(client):
    striker = create_player(client, full_name="Sam Finisher", primary_position="ST")
    winger = create_player(client, full_name="Lee Wide", primary_position="RW")
    _stat_line(client, striker, appearances=10, minutes_played=900, goals=6, shots=30, shots_on_target=12)
    _stat_line(client, winger, appearances=4, minutes_played=180, goals=1)  # no shots recorded at all

    body = client.get("/api/analytics/compare-players",
                      params={"player_ids": f"{striker['id']},{winger['id']}"}).json()
    first, second = body["players"]
    assert first["totals"]["goals"] == 6 and first["per_90"]["goals"] == pytest.approx(0.6)
    assert first["rates"]["shot_accuracy"] == {"value": pytest.approx(0.4), "from": "12 of 30"}
    assert second["totals"]["goals"] == 1 and second["per_90"]["goals"] == pytest.approx(0.5)
    # Never recorded stays None all the way through: not 0 shots, and no accuracy invented from nothing.
    assert second["totals"]["shots"] is None and second["per_90"]["shots"] is None
    assert second["rates"]["shot_accuracy"] == {"value": None, "from": None}
    assert second["totals"]["assists"] is None and first["totals"]["assists"] is None

    notes = " ".join(body["limitations"])
    assert "A bigger number does not make a better player" in notes
    assert "Lee Wide has only 180 recorded minutes" in notes
    assert "'shots' is not recorded for Lee Wide. Not recorded is not zero" in notes
    assert "better" not in notes.replace("does not make a better player", "")  # no verdict anywhere


def test_comparison_warns_about_different_roles_and_contexts(client):
    striker = create_player(client, full_name="Sam Finisher", primary_position="ST")
    keeper = create_player(client, full_name="Robin Keeper", primary_position="GK")
    unknown = create_player(client, full_name="No Numbers")
    _stat_line(client, striker, minutes_played=900, goals=6)
    _stat_line(client, keeper, minutes_played=900, goals=0, competition="Example Cup",
               source="A statistics website", extra_metrics={"saves": 31})

    body = client.get("/api/analytics/compare-players",
                      params={"player_ids": f"{striker['id']},{keeper['id']},{unknown['id']}"}).json()
    notes = " ".join(body["limitations"])
    assert "These players do different jobs" in notes
    assert "Sam Finisher (Forward)" in notes and "Robin Keeper (Goalkeeper)" in notes
    assert "No Numbers (position not recorded)" in notes
    assert "No Numbers has no season stat lines" in notes
    assert "do not cover the same matches or competitions" in notes
    assert "come from different sources" in notes
    assert body["players"][1]["totals"]["goals"] == 0  # a RECORDED zero is a real zero
    assert body["players"][2]["totals"]["goals"] is None  # nothing recorded is not

    # Narrowing to one competition leaves only the lines that belong to it.
    cup_id = client.get("/api/competitions").json()[0]["id"]  # "Example Cup" sorts first
    narrowed = client.get("/api/analytics/compare-players", params={
        "player_ids": f"{striker['id']},{keeper['id']}", "competition_id": cup_id}).json()
    assert [row["stat_lines"] for row in narrowed["players"]] == [0, 1]


def test_subjective_ratings_stay_separate_from_measured_numbers(client):
    striker = create_player(client, full_name="Sam Finisher", primary_position="ST")
    winger = create_player(client, full_name="Lee Wide", primary_position="RW")
    client.post(f"/api/players/{striker['id']}/assessments",
                json={"assessed_on": "2026-03-01", "ratings": [{"attribute": "finishing", "rating": 4}]})
    body = client.get("/api/analytics/compare-players",
                      params={"player_ids": f"{striker['id']},{winger['id']}"}).json()
    assert body["players"][0]["latest_assessment"]["ratings"] == {"finishing": 4}
    assert body["players"][1]["latest_assessment"] is None
    assert "finishing" not in body["players"][0]["totals"]  # an opinion is never listed among the statistics
    assert "subjective" in body["rating_scale_note"]


@pytest.mark.parametrize("params", [
    {"player_ids": "1"},  # one player is not a comparison
    {"player_ids": "1,1"},
    {"player_ids": "a,b"},
    {"player_ids": "1,2", "basis": "career"},
])
def test_invalid_comparisons_are_rejected(client, params):
    create_player(client, full_name="One")
    create_player(client, full_name="Two")
    assert client.get("/api/analytics/compare-players", params=params).status_code == 422


def test_comparing_a_missing_player_is_404(client):
    create_player(client, full_name="One")
    assert client.get("/api/analytics/compare-players", params={"player_ids": "1,99"}).status_code == 404
