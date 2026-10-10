"""Talking to Google's Gemini models. The ONLY file that does.

Needs no extra package: it makes one ordinary HTTPS request with httpx, which
the app already has installed.

The key is read from GEMINI_API_KEY (or GOOGLE_API_KEY), normally set in
backend/.env, each time a request is made. It travels in a request header, never
in the web address, and this file never stores, logs or returns it.

CHOICES MADE HERE, AND WHY
--------------------------
* responseMimeType "application/json" with responseJsonSchema: the answer
  arrives as data in a known shape, so the app can check every reference in it
  instead of trusting prose.
* If Google does not accept the schema setting, the same question is asked once
  more with the shape described in words instead. Either way the answer is
  checked by services/ai_service.py before you see it.
* The finish reason is looked at BEFORE the text: Google can stop because it
  declined, or because it ran out of room, and neither is a usable answer.
* A "busy" reply (500 or 503) is retried twice after a short wait, because on the
  free tier the model is sometimes overloaded for a few seconds.
* AI_EFFORT is not used here: Gemini decides by itself how much to reason.
* A long timeout, because a long answer can take a minute or more to write.
"""
import json
import logging
import os
import time
from urllib.parse import quote

import httpx

from errors import Unavailable
from services.ai.base import AIAnswer

logger = logging.getLogger("football")

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
MAX_OUTPUT_TOKENS = 16000
TIMEOUT = httpx.Timeout(180.0, connect=10.0)
# Google answers 500 or 503 when the model is briefly overloaded, which happens on the free tier.
# Those are worth asking again after a short wait (seconds) before giving up.
BUSY = (500, 503)
RETRY_WAITS = (2, 6)

# Finish reasons that mean "Google declined to answer", as opposed to "finished".
DECLINED = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "LANGUAGE", "ESCALATION"}


class GoogleProvider:
    name = "google"

    def __init__(self, model: str, effort: str, transport: httpx.BaseTransport | None = None):
        self.model = model.removeprefix("models/")
        self.effort = effort  # accepted so every provider is created the same way; not used
        self._transport = transport  # the tests pass a stand-in here, so nothing leaves the computer

    def complete(self, system: str, prompt: str, schema: dict) -> AIAnswer:
        key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
        if not key:
            raise Unavailable("AI is switched on, but no Google key was found. Put GEMINI_API_KEY in "
                              "backend/.env, then restart the server.")

        response = self._post(key, self._body(system, prompt, schema, with_schema=True))
        if response.status_code == 400 and "schema" in response.text.lower():
            logger.warning("Google did not accept the answer schema; asking again with the shape described in words")
            response = self._post(key, self._body(system, prompt, schema, with_schema=False))
        if response.status_code != 200:
            raise Unavailable(self._explain(response, key))
        return self._read(response)

    @staticmethod
    def _body(system: str, prompt: str, schema: dict, with_schema: bool) -> dict:
        generation = {"maxOutputTokens": MAX_OUTPUT_TOKENS, "responseMimeType": "application/json"}
        if with_schema:
            generation["responseJsonSchema"] = schema
        else:
            system += "\n\nAnswer with one JSON object that matches this JSON Schema exactly:\n" + json.dumps(schema)
        return {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": generation}

    def _post(self, key: str, body: dict) -> httpx.Response:
        url = f"{API_ROOT}/models/{quote(self.model, safe='')}:generateContent"
        try:
            with httpx.Client(timeout=TIMEOUT, transport=self._transport) as client:
                response = client.post(url, headers={"x-goog-api-key": key}, json=body)
                for wait in RETRY_WAITS:
                    if response.status_code not in BUSY:
                        break
                    time.sleep(wait)
                    response = client.post(url, headers={"x-goog-api-key": key}, json=body)
                return response
        except httpx.TimeoutException:
            raise Unavailable("The AI service took too long to answer. Try again later.") from None
        except httpx.HTTPError:
            raise Unavailable("Could not reach the AI service. Check the internet connection and try again.") from None

    def _explain(self, response: httpx.Response, key: str) -> str:
        """Turn a failed response into advice that actually helps. Never includes the key."""
        try:
            error = response.json().get("error") or {}
        except (ValueError, AttributeError):
            error = {}
        message = str(error.get("message") or "").replace(key, "[key hidden]")
        status = response.status_code
        if status in (401, 403) or "API_KEY_INVALID" in response.text or "API key not valid" in message:
            return "Google rejected the key. Check GEMINI_API_KEY in backend/.env, then restart the server."
        if status == 404:
            return f"The AI model '{self.model}' was not found. Check AI_MODEL in backend/.env."
        if status == 429:
            return ("Google's limit for this key has been reached. The free tier allows only so many requests "
                    "per minute and per day; wait a while and try again.")
        if status >= 500:
            return f"Google's AI service is busy or having a problem (status {status}). Try again in a minute."
        logger.warning("AI request rejected (status %s): %s", status, message)
        return f"The AI service did not accept the request: {message or f'status {status}'}"

    def _read(self, response: httpx.Response) -> AIAnswer:
        try:
            reply = response.json()
        except ValueError:
            reply = None
        if not isinstance(reply, dict):
            raise Unavailable("The AI answer could not be read. Nothing was changed; try again.")
        model = reply.get("modelVersion") or self.model

        # Always look at WHY the model stopped before reading what it wrote.
        candidates = reply.get("candidates") or []
        if (reply.get("promptFeedback") or {}).get("blockReason") or not candidates:
            return AIAnswer(data=None, model=model, refused=True)
        reason = candidates[0].get("finishReason")
        if reason in DECLINED:
            return AIAnswer(data=None, model=model, refused=True)
        if reason == "MAX_TOKENS":
            raise Unavailable("The AI answer was cut off before it finished. Try again with fewer records selected.")

        # Parts marked "thought" are the model's working-out, not the answer.
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
        try:
            data = json.loads(text) if text else None
        except json.JSONDecodeError:
            data = None
        if not isinstance(data, dict):
            raise Unavailable("The AI answer could not be read. Nothing was changed; try again.")
        return AIAnswer(data=data, model=model)
