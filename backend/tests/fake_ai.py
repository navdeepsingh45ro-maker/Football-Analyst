"""A stand-in AI provider for tests. It never contacts anything.

It records what it was asked and returns whatever answer the test prepared, so
the rules in services/ai_service.py can be checked without a real AI service.
"""
from services.ai.base import AIAnswer


class FakeProvider:
    name = "fake"
    calls: list[dict] = []  # every question asked, newest last
    next_answer: AIAnswer | None = None  # what the next call returns

    def __init__(self, model: str, effort: str):
        self.model = model
        self.effort = effort

    def complete(self, system: str, prompt: str, schema: dict) -> AIAnswer:
        FakeProvider.calls.append({"system": system, "prompt": prompt, "schema": schema})
        if FakeProvider.next_answer is None:
            raise AssertionError("The AI was called, but this test did not expect a call.")
        return FakeProvider.next_answer
