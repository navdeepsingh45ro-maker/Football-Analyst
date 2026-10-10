"""The Google (Gemini) provider, against a stand-in for Google's server.

No test here uses the network or a real key. httpx.MockTransport answers the
request inside this process, so we can check exactly what would be sent and how
every kind of reply is handled.
"""
import json

import httpx
import pytest

import config
from errors import Unavailable
from services import ai
from services.ai import google_provider
from services.ai.google_provider import GoogleProvider

KEY = "google-key-this-must-never-appear"
SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}, "additionalProperties": False}


def _reply(text='{"summary": "ok"}', finish="STOP", **extra) -> dict:
    parts = [{"text": "working it out", "thought": True}, {"text": text}]
    return {"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": finish}],
            "modelVersion": "gemini-3.8-flash-001", **extra}


def _provider(monkeypatch, *replies, key=KEY):
    """A provider whose requests are answered in turn by `replies`: (status, body) pairs or an exception."""
    if key:
        monkeypatch.setenv("GEMINI_API_KEY", key)
    monkeypatch.setattr(google_provider.time, "sleep", lambda seconds: None)  # no real waiting between retries
    queue, sent = list(replies), []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        status, body = reply
        return httpx.Response(status, json=body)

    return GoogleProvider(model="gemini-3.8-flash", effort="medium", transport=httpx.MockTransport(handler)), sent


def _error(status: int, message: str, reason: str | None = None) -> tuple[int, dict]:
    details = [{"reason": reason}] if reason else []
    return status, {"error": {"code": status, "message": message, "details": details}}


def test_the_request_is_built_the_documented_way(monkeypatch):
    provider, sent = _provider(monkeypatch, (200, _reply()))
    answer = provider.complete("system rules", "the records", SCHEMA)
    assert answer.data == {"summary": "ok"} and answer.refused is False
    assert answer.model == "gemini-3.8-flash-001"  # the model that really answered

    request = sent[0]
    assert str(request.url) == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"
    assert request.headers["x-goog-api-key"] == KEY and KEY not in str(request.url)  # header, never the address
    body = json.loads(request.content)
    assert body["systemInstruction"] == {"parts": [{"text": "system rules"}]}
    assert body["contents"] == [{"role": "user", "parts": [{"text": "the records"}]}]
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["responseJsonSchema"] == SCHEMA
    assert body["generationConfig"]["maxOutputTokens"] >= 4096


def test_the_models_working_out_is_not_mistaken_for_the_answer(monkeypatch):
    provider, _ = _provider(monkeypatch, (200, _reply(text='{"summary": "only this"}')))
    assert provider.complete("s", "p", SCHEMA).data == {"summary": "only this"}


def test_if_the_schema_setting_is_not_accepted_the_shape_is_described_in_words(monkeypatch):
    rejected = _error(400, "Invalid JSON payload received. Unknown name \"responseJsonSchema\" at 'generation_config'")
    provider, sent = _provider(monkeypatch, rejected, (200, _reply()))
    assert provider.complete("system rules", "p", SCHEMA).data == {"summary": "ok"}

    second = json.loads(sent[1].content)
    assert "responseJsonSchema" not in second["generationConfig"]
    assert second["generationConfig"]["responseMimeType"] == "application/json"
    instruction = second["systemInstruction"]["parts"][0]["text"]
    assert instruction.startswith("system rules") and json.dumps(SCHEMA) in instruction


def test_why_it_stopped_is_checked_before_the_answer_is_read(monkeypatch):
    for declined in ((200, _reply(text="", finish="SAFETY")),
                     (200, {"promptFeedback": {"blockReason": "PROHIBITED_CONTENT"}}),
                     (200, {"candidates": []})):
        provider, _ = _provider(monkeypatch, declined)
        answer = provider.complete("s", "p", SCHEMA)
        assert answer.refused is True and answer.data is None

    provider, _ = _provider(monkeypatch, (200, _reply(text='{"summary": "half an ans', finish="MAX_TOKENS")))
    with pytest.raises(Unavailable, match="cut off"):
        provider.complete("s", "p", SCHEMA)

    for unreadable in ("this is not JSON", "[1, 2, 3]", ""):
        provider, _ = _provider(monkeypatch, (200, _reply(text=unreadable)))
        with pytest.raises(Unavailable, match="could not be read"):
            provider.complete("s", "p", SCHEMA)


def test_every_kind_of_failure_gets_advice_and_never_the_key(monkeypatch):
    cases = [
        (_error(400, "API key not valid. Please pass a valid API key.", "API_KEY_INVALID"), "rejected the key"),
        (_error(403, "Permission denied."), "rejected the key"),
        (_error(404, "models/gemini-9 is not found."), "was not found"),
        (_error(429, "Quota exceeded."), "limit for this key"),
        (_error(400, f"Bad request for key {KEY}"), "did not accept the request"),
        (httpx.ConnectError("no route"), "Could not reach the AI service"),
        (httpx.ReadTimeout("slow"), "took too long"),
    ]
    for reply, expected in cases:
        provider, _ = _provider(monkeypatch, reply)
        with pytest.raises(Unavailable, match=expected) as raised:
            provider.complete("s", "p", SCHEMA)
        assert KEY not in raised.value.detail


def test_a_busy_service_is_asked_again_before_giving_up(monkeypatch):
    busy = _error(503, "The model is overloaded. Please try again later.")
    provider, sent = _provider(monkeypatch, busy, busy, (200, _reply()))
    assert provider.complete("s", "p", SCHEMA).data == {"summary": "ok"}
    assert len(sent) == 3

    provider, sent = _provider(monkeypatch, busy, busy, busy)
    with pytest.raises(Unavailable, match="status 503"):
        provider.complete("s", "p", SCHEMA)
    assert len(sent) == 3  # it does stop

    provider, sent = _provider(monkeypatch, _error(429, "Quota exceeded."))  # a limit is not "busy": no retry
    with pytest.raises(Unavailable, match="limit for this key"):
        provider.complete("s", "p", SCHEMA)
    assert len(sent) == 1


def test_without_a_key_nothing_is_sent(monkeypatch):
    provider, sent = _provider(monkeypatch, key=None)
    with pytest.raises(Unavailable, match="no Google key was found"):
        provider.complete("s", "p", SCHEMA)
    assert sent == []


def test_an_unreachable_service_is_explained(monkeypatch):
    # A real connection attempt to a closed port on this computer: nothing leaves the machine.
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    monkeypatch.setattr(google_provider, "API_ROOT", "http://127.0.0.1:9")
    with pytest.raises(Unavailable, match="Could not reach the AI service"):
        GoogleProvider(model="gemini-3.8-flash", effort="medium").complete("s", "p", SCHEMA)


def test_switching_it_on_picks_googles_own_default_model_and_reveals_nothing(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    monkeypatch.setattr(config, "AI_PROVIDER", "google")
    status = client.get("/api/ai/status")
    assert status.json()["enabled"] is True and status.json()["model"] == "gemini-3.8-flash"
    assert "must-never-appear" not in status.text

    provider = ai.get_provider()
    assert isinstance(provider, GoogleProvider) and provider.model == "gemini-3.8-flash"

    monkeypatch.setattr(config, "AI_MODEL", "models/gemini-3.5-flash-lite")  # either spelling of a model name works
    assert ai.get_provider().model == "gemini-3.5-flash-lite"
