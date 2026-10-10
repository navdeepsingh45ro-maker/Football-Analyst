"""Optional AI assistance: which provider is switched on, if any.

AI IS AN EXTRA. Nothing else in the app imports this package, so every other
feature works identically whether AI is configured, misconfigured or absent.

HOW THE PIECES FIT
------------------
    services/ai/base.py                what any AI provider must be able to do
    services/ai/google_provider.py     the ONE file that talks to Google (Gemini)
    services/ai/anthropic_provider.py  the ONE file that talks to Anthropic (Claude)
    services/ai/__init__.py            (this file) picks the provider from the settings
    services/ai_service.py             builds the question from YOUR stored records and
                                       checks the answer's references. Knows no provider.

To use a different AI company later: write one new provider file with the same
`complete()` method and add it to PROVIDERS below. Nothing else changes.

SETTINGS (backend/.env, see config.py)
    AI_PROVIDER=google        switches AI on (or: anthropic). Leave it out and AI is off.
    AI_MODEL=...              optional; which model to use. Empty means the provider's
                              own default from DEFAULT_MODELS below.
    GEMINI_API_KEY=...        the key for google;  ANTHROPIC_API_KEY=... for anthropic
The key is read from the environment by the provider file only. This app never
stores, logs or returns it.
"""
from importlib import import_module

import config
from errors import Unavailable
from services.ai.base import AIAnswer, AIProvider

# name used in AI_PROVIDER -> (module, class)
PROVIDERS = {
    "google": ("services.ai.google_provider", "GoogleProvider"),
    "anthropic": ("services.ai.anthropic_provider", "AnthropicProvider"),
}

# Each company has its own model names, so the model used when AI_MODEL is empty depends on the provider.
DEFAULT_MODELS = {"google": "gemini-3.8-flash", "anthropic": "claude-opus-5-5"}

__all__ = ["AIAnswer", "AIProvider", "DEFAULT_MODELS", "PROVIDERS", "get_provider", "status"]


def model_in_use() -> str:
    return config.AI_MODEL or DEFAULT_MODELS.get(config.AI_PROVIDER, "")


def status() -> dict:
    """Whether AI is switched on, in words. Never includes a key or any other secret."""
    name = config.AI_PROVIDER
    if not name:
        return {"enabled": False, "provider": None, "model": None,
                "message": "AI assistance is off. Everything else works without it. To switch it on, see "
                           "\"Optional AI\" in the README."}
    if name not in PROVIDERS:
        return {"enabled": False, "provider": name, "model": None,
                "message": f"AI_PROVIDER is set to '{name}', which this app does not know. "
                           f"Known providers: {', '.join(PROVIDERS)}."}
    return {"enabled": True, "provider": name, "model": model_in_use(),
            "message": f"AI assistance is on ({name}, model {model_in_use()}). Its credentials are checked the "
                       "first time you use it. What is sent is described on the Coach page."}


def get_provider() -> AIProvider:
    """The configured provider, ready to use. Raises Unavailable (503) with the reason if there is none."""
    current = status()
    if not current["enabled"]:
        raise Unavailable(current["message"])
    module_name, class_name = PROVIDERS[config.AI_PROVIDER]
    provider_class = getattr(import_module(module_name), class_name)
    return provider_class(model=model_in_use(), effort=config.AI_EFFORT)
