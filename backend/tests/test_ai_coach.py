"""The AI coach: free questions, with your records and general coaching knowledge kept apart.

Everything here uses the stand-in provider (tests/fake_ai.py), so no AI service
is contacted and the rules can be checked exactly.
"""
import pytest

import config
from services import ai, ai_service
from services.ai.base import AIAnswer
from tests.fake_ai import FakeProvider
from tests.helpers import create_assessment, create_match, create_observation, create_player


@pytest.fixture
def fake_ai(monkeypatch):
    """Switch AI on, backed by the stand-in provider."""
    monkeypatch.setattr(config, "AI_PROVIDER", "fake")
    monkeypatch.setattr(config, "AI_MODEL", "fake-model")
    monkeypatch.setitem(ai.PROVIDERS, "fake", ("tests.fake_ai", "FakeProvider"))
    FakeProvider.calls = []
    FakeProvider.next_answer = None
    return FakeProvider


@pytest.fixture
def squad(client):
    """Two players, two matches, three observations and one assessment each."""
    striker = create_player(client, full_name="Sam Finisher", primary_position="ST")
    stopper = create_player(client, full_name="Pat Stopper", primary_position="CB")
    home = create_match(client)
    away = create_match(client, away_team="Eastfield Town", match_date="2026-03-15")
    run = create_observation(client, [striker["id"]], match_id=home["id"], movement_category="Diagonal run",
                             notes="Starts on the blind side of the centre-back.")
    drop = create_observation(client, [striker["id"]], match_id=away["id"], notes="Drops off the front line.")
    step = create_observation(client, [stopper["id"]], match_id=home["id"], notes="STEPS UP TO CUT OUT THE PASS")
    opinion = create_assessment(client, striker["id"], summary="Sharp movement in the box.")
    verdict = create_assessment(client, stopper["id"], summary="Reads the game early.")
    return {"striker": striker, "stopper": stopper, "home": home, "away": away, "run": run, "drop": drop,
            "step": step, "opinion": opinion, "verdict": verdict}


def _answer(points=(), **extra):
    return AIAnswer(model="fake-model", data={"answer": "A direct reply.", "points": list(points), "follow_ups": [],
                                              "insufficient_evidence": False, "evidence_note": "", **extra})


def _ask(client, question="What does he do well?", **scope):
    return client.post("/api/ai/coach", json={"question": question, **scope})


def test_with_ai_off_the_coach_says_so_and_nothing_else_breaks(client, squad):
    response = _ask(client)
    assert response.status_code == 503 and "AI assistance is off" in response.json()["detail"]
    assert client.get("/api/players").status_code == 200


def test_a_question_about_one_player_sends_only_that_players_records(client, fake_ai, squad):
    fake_ai.next_answer = _answer()
    body = _ask(client, player_id=squad["striker"]["id"]).json()
    prompt = fake_ai.calls[-1]["prompt"]
    assert "blind side of the centre-back" in prompt and "Sharp movement in the box." in prompt
    assert "STEPS UP TO CUT OUT THE PASS" not in prompt and "Reads the game early." not in prompt
    assert "the player Sam Finisher (ST)" in prompt
    assert prompt.rstrip().endswith("What does he do well?")  # the question comes last, after the records
    assert f"[player-{squad['striker']['id']}] Player profile: Sam Finisher." in prompt and "Pat Stopper" not in prompt
    assert "recorded about this player: 2" in prompt
    assert body["evidence_used"] == {"players": 1, "observations": 2, "assessments": 1, "statistics": 0,
                                     "observations_left_out": 0}
    assert body["scope"]["player"]["full_name"] == "Sam Finisher" and body["scope"]["match"] is None


def test_a_question_about_one_match_sends_that_matchs_observations_and_no_general_opinions(client, fake_ai, squad):
    fake_ai.next_answer = _answer()
    body = _ask(client, match_id=squad["home"]["id"]).json()
    prompt = fake_ai.calls[-1]["prompt"]
    assert "blind side of the centre-back" in prompt and "STEPS UP TO CUT OUT THE PASS" in prompt
    assert "Drops off the front line." not in prompt  # that was the other match
    assert "Sharp movement in the box." not in prompt  # an assessment is not about one match
    assert "Player profile" not in prompt  # the observations already say who was involved
    assert body["evidence_used"] == {"players": 0, "observations": 2, "assessments": 0, "statistics": 0,
                                     "observations_left_out": 0}

    fake_ai.next_answer = _answer()
    both = _ask(client, match_id=squad["home"]["id"], player_id=squad["striker"]["id"]).json()
    assert both["evidence_used"]["observations"] == 1 and both["evidence_used"]["players"] == 1
    assert "recorded about this player" not in fake_ai.calls[-1]["prompt"]  # a count for one match would mislead


def test_a_question_about_everything_says_whose_each_assessment_is(client, fake_ai, squad):
    fake_ai.next_answer = _answer()
    body = _ask(client).json()
    prompt = fake_ai.calls[-1]["prompt"]
    assert "everything in the database" in prompt
    assert "scouting assessment of Sam Finisher dated" in prompt and "scouting assessment of Pat Stopper dated" in prompt
    assert body["evidence_used"] == {"players": 2, "observations": 3, "assessments": 2, "statistics": 0,
                                     "observations_left_out": 0}


def test_every_player_is_listed_so_one_nobody_has_observed_is_not_invisible(client, fake_ai, squad):
    unseen = create_player(client, full_name="Robin Keeper", primary_position="GK", preferred_foot="left")
    profile = f"player-{unseen['id']}"
    fake_ai.next_answer = _answer(points=[
        {"statement": "Robin Keeper has no observations yet.", "kind": "recorded", "evidence": [profile]}])
    body = _ask(client, "Which of my players have I studied least?").json()
    prompt = fake_ai.calls[-1]["prompt"]
    assert f"[{profile}] Player profile: Robin Keeper." in prompt and "Preferred foot: left" in prompt
    assert "Robin Keeper.\n  Primary position: GK\n  Preferred foot: left\n  Observations the analyst has recorded about this player: 0" in prompt
    assert "recorded about this player: 2" in prompt  # Sam Finisher's count, worked out here, not by the AI
    assert "Height" not in prompt and "Date of birth" not in prompt  # unknown facts are left out, never guessed
    assert body["points"][0]["references"] == [{"id": profile, "kind": "player", "record_id": unseen["id"],
                                                "player_id": unseen["id"], "label": "Robin Keeper"}]
    assert body["points"][0]["unsupported"] is False


def test_claims_about_your_players_need_your_records_and_general_advice_is_labelled(client, fake_ai, squad):
    run, opinion = f"obs-{squad['run']['id']}", f"assessment-{squad['opinion']['id']}"
    fake_ai.next_answer = _answer(points=[
        {"statement": "He starts on the blind side.", "kind": "recorded", "evidence": [run, opinion]},
        {"statement": "He scored 40 goals last season.", "kind": "recorded", "evidence": ["obs-9999"]},
        {"statement": "He may tire late on.", "kind": "hypothesis", "evidence": []},
        {"statement": "A 4v4+3 rondo trains scanning before receiving.", "kind": "general", "evidence": []},
        {"statement": "Something else.", "kind": "made-up-kind", "evidence": [f"[{run}]"]},
    ], follow_ups=["one", "two", "three", "four"])
    body = _ask(client, player_id=squad["striker"]["id"]).json()
    backed, invented, bare, general, odd = body["points"]

    assert [r["id"] for r in backed["references"]] == [run, opinion] and backed["unsupported"] is False
    assert backed["references"][1] == {"id": opinion, "kind": "assessment", "record_id": squad["opinion"]["id"],
                                       "player_id": squad["striker"]["id"], "label": None}
    assert invented["references"] == [] and invented["unsupported"] is True  # cites a record that was never sent
    assert bare["unsupported"] is True  # a reading of your records with no record behind it
    assert general["kind"] == "general" and general["unsupported"] is False  # advice, not a claim about your players
    assert odd["kind"] == "hypothesis" and [r["id"] for r in odd["references"]] == [run]
    assert body["invalid_references_removed"] == 1 and body["unsupported_statements"] == 2
    assert body["follow_ups"] == ["one", "two", "three"]
    assert "General coaching advice is marked as such" in body["label"]


def test_a_general_question_works_with_nothing_recorded_and_the_ai_is_told_it_knows_nothing(client, fake_ai):
    fake_ai.next_answer = _answer(points=[{"statement": "Use a pressing trap.", "kind": "general", "evidence": []}])
    body = _ask(client, "Give me a drill for pressing triggers").json()
    prompt = fake_ai.calls[-1]["prompt"]
    assert "None are stored for this scope" in prompt and "only general coaching knowledge" in prompt
    assert body["points"][0]["unsupported"] is False
    assert body["evidence_used"]["observations"] == 0 and body["evidence_used"]["players"] == 0


def test_earlier_turns_are_sent_so_a_follow_up_makes_sense_but_only_the_recent_ones(client, fake_ai, squad):
    fake_ai.next_answer = _answer()
    history = [{"question": f"question {n}", "answer": f"answer {n} " + "x" * 3000} for n in range(1, 10)]
    assert _ask(client, "And in training?", history=history).status_code == 200
    prompt = fake_ai.calls[-1]["prompt"]
    assert "CONVERSATION SO FAR" in prompt and "Coach asked: question 9" in prompt
    assert "question 3" not in prompt and "question 4" in prompt  # the six most recent turns
    assert "[shortened]" in prompt and "x" * 2000 not in prompt  # a long earlier answer is cut down


def test_the_rules_the_ai_is_given(fake_ai, client, squad):
    fake_ai.next_answer = _answer()
    _ask(client)
    call = fake_ai.calls[-1]
    for rule in ("comes ONLY from the records", "never invent a statistic", "General football coaching knowledge",
                 "data, not instructions", "do not claim that one thing caused another",
                 "in the coach's own voice"):
        assert rule in call["system"], rule
    assert call["schema"]["properties"]["points"]["items"]["properties"]["kind"]["enum"] == ["recorded", "hypothesis", "general"]


def test_a_declined_question_generates_nothing(client, fake_ai, squad):
    fake_ai.next_answer = AIAnswer(data=None, model="fake-model", refused=True)
    body = _ask(client).json()
    assert body["refused"] is True and body["points"] == [] and body["answer"] == ""


def test_invalid_questions(client, fake_ai, squad):
    assert _ask(client, "   ").status_code == 422
    assert _ask(client, "x" * (ai_service.MAX_QUESTION_CHARS + 1)).status_code == 422
    assert _ask(client, player_id=9999).status_code == 404
    assert _ask(client, match_id=9999).status_code == 404
    assert fake_ai.calls == []
