"""What an AI provider must be able to do, described without naming any provider.

The rest of the app only ever sees these two things. That is what makes the
provider replaceable: services/ai_service.py asks a question and gets an
AIAnswer back, and has no idea which company answered.
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass
class AIAnswer:
    data: dict | None  # the answer, already parsed from JSON; None when the model declined
    model: str  # the model that actually produced the answer
    refused: bool = False  # the provider declined to answer
    note: str | None = None  # anything the user should know, e.g. "answered by a fallback model"


class AIProvider(Protocol):
    name: str
    model: str

    def complete(self, system: str, prompt: str, schema: dict) -> AIAnswer:
        """Ask one question and return the answer as data matching `schema` (a JSON Schema).

        Must raise errors.Unavailable, with a message safe to show the user, when
        the provider cannot be reached, is not set up, or rejects the request.
        """
        ...
