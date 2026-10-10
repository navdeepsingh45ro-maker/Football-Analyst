"""Talking to Claude through Anthropic's official SDK. The ONLY file that does.

Needs the optional package:   pip install -r requirements-ai.txt
Credentials are found by the SDK itself, in this order: the ANTHROPIC_API_KEY
environment variable (which may be set in backend/.env), ANTHROPIC_AUTH_TOKEN,
or a login made with Anthropic's `ant auth login` command. This file never
reads, stores or logs them.

CHOICES MADE HERE, AND WHY
--------------------------
* Streaming, then get_final_message(): the request cannot time out while a long
  answer is being written, and we still get one complete message at the end.
* output_config.format with a JSON schema: the answer arrives as data in a known
  shape, so the app can check every reference in it instead of trusting prose.
* output_config.effort: how thoroughly the model works (and what it costs). Set
  with AI_EFFORT; "medium" is this model's default.
* fallbacks="default": if the main model's safety checks decline a request, the
  API retries it on the model Anthropic recommends for that case, inside the same
  call. It is a beta feature, hence `client.beta` and the beta name below.
* `thinking` is deliberately not sent: on the default model it is always on and
  adapts by itself.
"""
import json
import logging

from errors import Unavailable
from services.ai.base import AIAnswer

logger = logging.getLogger("football")

FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_OUTPUT_TOKENS = 16000


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str, effort: str):
        try:
            import anthropic  # imported here so the app starts fine without the package
        except ModuleNotFoundError:
            raise Unavailable("AI is switched on, but the 'anthropic' package is not installed. In the backend "
                              "folder run: pip install -r requirements-ai.txt") from None
        self._anthropic = anthropic
        self._client = anthropic.Anthropic()
        self.model = model
        self.effort = effort

    def complete(self, system: str, prompt: str, schema: dict) -> AIAnswer:
        anthropic = self._anthropic
        try:
            with self._client.beta.messages.stream(
                model=self.model,
                max_tokens=MAX_OUTPUT_TOKENS,
                betas=[FALLBACK_BETA],
                fallbacks="default",
                output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
                system=system,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                message = stream.get_final_message()
        # Most specific first, so each kind of failure gets advice that actually helps.
        except anthropic.AuthenticationError:
            raise Unavailable("The AI service rejected the credentials. Check ANTHROPIC_API_KEY in backend/.env, "
                              "or log in again with `ant auth login`.") from None
        except anthropic.PermissionDeniedError:
            raise Unavailable("These AI credentials are not allowed to use this model or feature.") from None
        except anthropic.NotFoundError:
            raise Unavailable(f"The AI model '{self.model}' was not found. Check AI_MODEL in backend/.env.") from None
        except anthropic.RateLimitError:
            raise Unavailable("The AI service is limiting requests right now. Wait a minute and try again.") from None
        except anthropic.BadRequestError as error:
            logger.warning("AI request rejected: %s", error.message)
            raise Unavailable(f"The AI service did not accept the request: {error.message}") from None
        except anthropic.APIStatusError as error:
            raise Unavailable(f"The AI service had a problem (status {error.status_code}). Try again later.") from None
        except anthropic.APIConnectionError:
            raise Unavailable("Could not reach the AI service. Check the internet connection and try again.") from None
        except TypeError as error:
            # What the SDK raises when it finds no credentials at all.
            logger.warning("AI credentials could not be resolved: %s", error)
            raise Unavailable("AI is switched on, but no credentials were found. Put ANTHROPIC_API_KEY in "
                              "backend/.env, or log in with `ant auth login`, then restart the server.") from None

        # Always look at WHY the model stopped before reading what it wrote.
        if message.stop_reason == "refusal":
            return AIAnswer(data=None, model=message.model, refused=True)
        if message.stop_reason == "max_tokens":
            raise Unavailable("The AI answer was cut off before it finished. Try again with fewer records selected.")

        text = next((block.text for block in message.content if block.type == "text"), None)
        try:
            data = json.loads(text) if text else None
        except json.JSONDecodeError:
            data = None
        if not isinstance(data, dict):
            raise Unavailable("The AI answer could not be read. Nothing was changed; try again.")

        # A fallback model may have answered instead of the one asked for. Say so.
        iterations = getattr(message.usage, "iterations", None) or []
        fell_back = any(getattr(entry, "type", None) == "fallback_message" for entry in iterations)
        note = (f"The requested model declined, so the answer came from {message.model}." if fell_back else None)
        return AIAnswer(data=data, model=message.model, note=note)
