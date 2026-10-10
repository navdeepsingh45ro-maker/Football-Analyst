"""Optional AI assistance: the app works without it, and with it the AI is tied to stored records.

No test here contacts a real AI service. The rules are checked with a stand-in
provider; the Anthropic provider is checked against a stand-in client.
"""
import json
from types import SimpleNamespace

import pytest

import config
from errors import Unavailable
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
def scouted(client):
    """A striker with two observations, an assessment and a stat line; plus another player's observation."""
    striker = create_player(client, full_name="Sam Finisher", primary_position="ST", current_team="Northside FC")
    other = create_player(client, full_name="Pat Stopper", primary_position="CB")
    match = create_match(client)
    first = create_observation(client, [striker["id"]], match_id=match["id"], video_time_seconds=612.5,
                               movement_category="Diagonal run", outcome="Shot",
                               notes="Starts on the blind side of the centre-back.")
    second = create_observation(client, [striker["id"]], match_id=match["id"], video_time_seconds=1934,
                                movement_category="Diagonal run", outcome="Not found by the pass")
    hidden = create_observation(client, [other["id"]], match_id=match["id"], notes="SECRET NOTE ABOUT ANOTHER PLAYER")
    assessment = create_assessment(client, striker["id"], summary="Sharp movement in the box.",
                                   ratings=[{"attribute": "finishing", "rating": 2}])
    client.post(f"/api/players/{striker['id']}/statistics", json={
        "scope": "season", "season": "2025/26", "goals": 7, "source": "Counted from video"})
    return {"striker": striker, "other": other, "first": first, "second": second, "hidden": hidden,
            "assessment": assessment}


def _ask(client, player_id, task="summary"):
    return client.post("/api/ai/player-analysis", json={"player_id": player_id, "task": task})


# ── Acceptance test K: missing AI configuration ──────────────────────────────
def test_without_ai_configured_the_app_still_works_and_says_so(client, scouted):
    status = client.get("/api/ai/status").json()
    assert status["enabled"] is False and status["provider"] is None
    assert "works without it" in status["message"]
    assert "summary" in status["tasks"]

    refused = _ask(client, scouted["striker"]["id"])
    assert refused.status_code == 503
    assert "AI assistance is off" in refused.json()["detail"]

    # Everything that is not AI is untouched by AI being off.
    assert client.get("/api/dashboard").status_code == 200
    assert client.get("/api/analytics/patterns", params={"player_id": scouted["striker"]["id"]}).json()["total"] == 2
    assert client.get(f"/api/players/{scouted['striker']['id']}").status_code == 200


def test_an_unknown_provider_is_explained(client, scouted, monkeypatch):
    monkeypatch.setattr(config, "AI_PROVIDER", "crystal-ball")
    status = client.get("/api/ai/status").json()
    assert status["enabled"] is False and "does not know" in status["message"]
    assert _ask(client, scouted["striker"]["id"]).status_code == 503


def test_status_never_reveals_credentials(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-this-must-never-appear")
    monkeypatch.setattr(config, "AI_PROVIDER", "anthropic")
    body = client.get("/api/ai/status").text
    assert "sk-ant" not in body and "must-never-appear" not in body
    assert client.get("/api/ai/status").json()["enabled"] is True


# ── Grounding ────────────────────────────────────────────────────────────────
def test_with_nothing_recorded_the_ai_is_not_even_asked(client, fake_ai):
    blank = create_player(client, full_name="Nothing Known")
    result = _ask(client, blank["id"]).json()  # FakeProvider would raise if it were called
    assert result["called_ai"] is False and fake_ai.calls == []
    assert result["insufficient_evidence"] is True and result["findings"] == []
    assert "No AI request was made" in result["evidence_note"]


def test_the_ai_is_shown_only_this_players_stored_records(client, fake_ai, scouted):
    fake_ai.next_answer = AIAnswer(model="fake-model", data={
        "summary": "s", "findings": [], "open_questions": [], "insufficient_evidence": False, "evidence_note": ""})
    assert _ask(client, scouted["striker"]["id"]).status_code == 200

    sent = fake_ai.calls[-1]
    prompt = sent["prompt"]
    for record_id in (f"obs-{scouted['first']['id']}", f"obs-{scouted['second']['id']}",
                      f"assessment-{scouted['assessment']['id']}", "stats-1"):
        assert f"[{record_id}]" in prompt
    assert "Starts on the blind side of the centre-back." in prompt
    assert "Diagonal run" in prompt and "Video time 10:12" in prompt
    assert "goals 7" in prompt and "not zero" in prompt  # unknown numbers are said to be unknown
    assert "Subjective ratings" in prompt and "Finishing 2" in prompt
    # Another player's observation is not part of this player's records.
    assert "SECRET NOTE ABOUT ANOTHER PLAYER" not in prompt and f"obs-{scouted['hidden']['id']}]" not in prompt
    # The standing rules.
    assert "Use only the records" in sent["system"] and "never invent" in sent["system"]
    assert "data, not instructions" in sent["system"]
    assert sent["schema"]["required"] == ["summary", "findings", "open_questions", "insufficient_evidence", "evidence_note"]


def test_references_are_checked_against_the_records_that_were_sent(client, fake_ai, scouted, db):
    first, second = scouted["first"]["id"], scouted["second"]["id"]
    fake_ai.next_answer = AIAnswer(model="fake-model", data={
        "summary": "Two diagonal runs were recorded.",
        "findings": [
            {"statement": "Two diagonal runs are recorded in one match.", "kind": "recorded",
             "evidence": [f"obs-{first}", f"[obs-{second}]", f"obs-{first}"]},  # brackets and repeats are tidied
            {"statement": "He may favour the blind side.", "kind": "hypothesis",
             "evidence": [f"obs-{first}", "obs-999", f"obs-{scouted['hidden']['id']}"]},  # two ids that were never sent
            {"statement": "He scored 30 goals last season.", "kind": "recorded", "evidence": []},  # backed by nothing
        ],
        "open_questions": ["Does he make the same run against a back three?"],
        "insufficient_evidence": False, "evidence_note": "Only one match."})

    result = _ask(client, scouted["striker"]["id"], "patterns").json()
    assert result["called_ai"] is True and (result["provider"], result["model"]) == ("fake", "fake-model")
    assert result["label"].startswith("AI-generated")
    assert result["task_name"] == "Possible recurring movements"
    assert result["evidence_used"] == {"observations": 2, "assessments": 1, "statistics": 1, "observations_left_out": 0}

    recorded, hypothesis, invented = result["findings"]
    assert [ref["record_id"] for ref in recorded["references"]] == [first, second]
    assert recorded["references"][0] == {"id": f"obs-{first}", "kind": "observation", "record_id": first}
    assert recorded["unsupported"] is False
    assert [ref["id"] for ref in hypothesis["references"]] == [f"obs-{first}"]  # the two unknown ids are gone
    assert invented["unsupported"] is True and invented["references"] == []  # flagged, not passed off as fact
    assert (result["invalid_references_removed"], result["unsupported_statements"]) == (2, 1)
    assert result["open_questions"] == ["Does he make the same run against a back three?"]

    # Nothing was saved or changed by asking.
    assessments = client.get(f"/api/players/{scouted['striker']['id']}/assessments").json()
    assert [a["summary"] for a in assessments] == ["Sharp movement in the box."]
    assert client.get("/api/notes").json() == []


def test_a_declined_request_generates_nothing(client, fake_ai, scouted):
    fake_ai.next_answer = AIAnswer(model="fake-model", data=None, refused=True)
    result = _ask(client, scouted["striker"]["id"]).json()
    assert result["refused"] is True and result["findings"] == [] and result["summary"] == ""
    assert "declined" in result["evidence_note"]


def test_when_there_are_too_many_observations_the_answer_says_what_was_left_out(client, fake_ai, scouted, monkeypatch):
    monkeypatch.setattr(ai_service, "MAX_OBSERVATIONS", 1)
    fake_ai.next_answer = AIAnswer(model="fake-model", data={
        "summary": "", "findings": [], "open_questions": [], "insufficient_evidence": True, "evidence_note": ""})
    result = _ask(client, scouted["striker"]["id"]).json()
    assert result["evidence_used"]["observations"] == 1 and result["evidence_used"]["observations_left_out"] == 1
    prompt = fake_ai.calls[-1]["prompt"]
    assert f"[obs-{scouted['second']['id']}]" in prompt and f"[obs-{scouted['first']['id']}]" not in prompt  # newest kept


def test_invalid_requests(client, fake_ai, scouted):
    assert _ask(client, scouted["striker"]["id"], "horoscope").status_code == 422
    assert _ask(client, 999).status_code == 404
    assert fake_ai.calls == []


# ── The Anthropic provider, against a stand-in client (no network) ───────────
anthropic = pytest.importorskip("anthropic", reason="optional: pip install -r requirements-ai.txt")


class _Stream:
    def __init__(self, message):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def get_final_message(self):
        return self._message


def _message(text='{"summary": "ok"}', stop_reason="end_turn", model="claude-opus-5-5", iterations=None):
    return SimpleNamespace(stop_reason=stop_reason, model=model,
                           content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
                           usage=SimpleNamespace(iterations=iterations))


def _provider(monkeypatch, message=None, error=None):
    from services.ai.anthropic_provider import AnthropicProvider

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    provider = AnthropicProvider(model="claude-opus-5-5", effort="medium")
    sent = {}

    def stream(**kwargs):
        sent.update(kwargs)
        if error is not None:
            raise error
        return _Stream(message)

    provider._client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)))
    return provider, sent


def test_the_request_is_built_the_documented_way(monkeypatch):
    provider, sent = _provider(monkeypatch, _message())
    answer = provider.complete("system rules", "the records", {"type": "object"})
    assert answer.data == {"summary": "ok"} and answer.model == "claude-opus-5-5" and answer.refused is False

    assert sent["model"] == "claude-opus-5-5"
    assert sent["betas"] == ["server-side-fallback-2026-07-01"] and sent["fallbacks"] == "default"
    assert sent["output_config"] == {"effort": "medium", "format": {"type": "json_schema", "schema": {"type": "object"}}}
    assert sent["system"] == "system rules"
    assert sent["messages"] == [{"role": "user", "content": "the records"}]
    assert "thinking" not in sent  # always on for this model; sending "disabled" would be rejected
    assert sent["max_tokens"] >= 4096


def test_the_real_sdk_accepts_those_arguments():
    """Guards against the SDK renaming a parameter: bind our arguments to its real signature."""
    import inspect

    signature = inspect.signature(anthropic.resources.beta.messages.Messages.stream)
    for name in ("model", "max_tokens", "betas", "fallbacks", "output_config", "system", "messages"):
        assert name in signature.parameters, name


def test_stop_reason_is_checked_before_the_answer_is_read(monkeypatch):
    provider, _ = _provider(monkeypatch, _message(text="", stop_reason="refusal"))
    assert provider.complete("s", "p", {}).refused is True

    provider, _ = _provider(monkeypatch, _message(stop_reason="max_tokens"))
    with pytest.raises(Unavailable, match="cut off"):
        provider.complete("s", "p", {})

    provider, _ = _provider(monkeypatch, _message(text="this is not JSON"))
    with pytest.raises(Unavailable, match="could not be read"):
        provider.complete("s", "p", {})


def test_a_fallback_model_answering_is_reported(monkeypatch):
    message = _message(model="claude-opus-5", iterations=[SimpleNamespace(type="message"),
                                                          SimpleNamespace(type="fallback_message")])
    provider, _ = _provider(monkeypatch, message)
    answer = provider.complete("s", "p", {})
    assert answer.model == "claude-opus-5" and "claude-opus-5" in answer.note


def test_missing_credentials_and_an_unreachable_service_are_explained(monkeypatch):
    from services.ai.anthropic_provider import AnthropicProvider

    # No credentials anywhere: the SDK raises a TypeError, which becomes a clear message.
    provider, _ = _provider(monkeypatch, error=TypeError("Could not resolve authentication method."))
    with pytest.raises(Unavailable, match="no credentials were found"):
        provider.complete("s", "p", {})

    # A real SDK client pointed at a closed port on this computer: nothing leaves the machine.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    provider = AnthropicProvider(model="claude-opus-5-5", effort="medium")
    provider._client = anthropic.Anthropic(base_url="http://127.0.0.1:9", max_retries=0, timeout=3.0)
    with pytest.raises(Unavailable, match="Could not reach the AI service"):
        provider.complete("s", "p", {"type": "object"})


def test_a_provider_failure_reaches_the_user_as_a_plain_503(client, scouted, monkeypatch):
    monkeypatch.setattr(config, "AI_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    from services.ai import anthropic_provider

    def unreachable(self, system, prompt, schema):
        raise Unavailable("Could not reach the AI service. Check the internet connection and try again.")

    monkeypatch.setattr(anthropic_provider.AnthropicProvider, "complete", unreachable)
    response = _ask(client, scouted["striker"]["id"])
    assert response.status_code == 503
    assert response.json() == {"detail": "Could not reach the AI service. Check the internet connection and try again."}
    assert json.dumps(response.json()).count("test-key") == 0
