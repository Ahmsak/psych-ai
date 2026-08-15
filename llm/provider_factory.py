"""Provider factory — the single swap point for LLM backends.

The rest of the application (Orchestrator, UI) depends ONLY on this factory
and the ``LLMProvider`` contract. To add a new backend (Alem, DeepSeek,
Kimi, OpenAI, ...) you implement a subclass of ``LLMProvider`` in this
package and register it in ``PROVIDER_REGISTRY`` below — NOTHING else in
the app changes.

The active provider is selected by the developer through PSYCHAI_LLM_PROVIDER;
the UI never chooses a provider (per Sprint 17 scope).
"""

from __future__ import annotations

from typing import Dict, Type

from llm.config import LLMConfig
from llm.contract import LLMProvider
from llm.gemini import GeminiProvider


PROVIDER_REGISTRY: Dict[str, Type[LLMProvider]] = {
    "gemini": GeminiProvider,
}


class UnknownProviderError(ValueError):
    """Raised when the configured provider key is not registered."""


def get_provider(config: LLMConfig) -> LLMProvider:
    """Resolve an ``LLMProvider`` from an ``LLMConfig``.

    Raises ``UnknownProviderError`` if the provider key is unknown. The
    provider constructor is responsible for validating its own API key.
    """
    key = (config.provider or "").strip().lower()
    cls = PROVIDER_REGISTRY.get(key)
    if cls is None:
        available = ", ".join(sorted(PROVIDER_REGISTRY)) or "(none)"
        raise UnknownProviderError(
            f"Unknown LLM provider '{config.provider}'. "
            f"Registered providers: {available}."
        )
    return cls(config)
