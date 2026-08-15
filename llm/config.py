"""LLM runtime configuration.

The active provider and model are set by the DEVELOPER through
environment variables — the UI never selects a provider or model (per
Sprint 17 scope). API keys are ONLY ever read from the environment (or a
``.env`` loaded by python-dotenv if present); they are never hardcoded,
never written to the database, never written to git, and never logged.

Environment variables:
    PSYCHAI_LLM_PROVIDER  active provider registry key (default: "gemini")
    PSYCHAI_LLM_MODEL     model id (default: provider-specific; see Gemini)
    GEMINI_API_KEY        Gemini API key (required for the gemini provider)

python-dotenv is used if importable; its absence is not an error (env vars
may already be exported). We deliberately avoid adding it as a hard project
dependency — the rest of the app does not need it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


# Default model chosen after a sanity-check of the Gemini model catalogue:
# gemini-2.5-flash is stable, cheap, and has a 1M-token context window —
# comfortably enough for even long session transcripts. Override via
# PSYCHAI_LLM_MODEL at any time without code changes.
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
PROVIDER_ENV = "PSYCHAI_LLM_PROVIDER"
MODEL_ENV = "PSYCHAI_LLM_MODEL"


def _load_dotenv_if_available() -> None:
    """Best-effort .env loader; never raises if dotenv is absent."""
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    try:
        load_dotenv()
    except Exception:
        return


@dataclass
class LLMConfig:
    """Resolved LLM configuration for this run.

    ``provider`` is the registry key (e.g. "gemini"). ``model`` is the
    concrete model id. ``api_key`` is provider-specific and opaque to the
    rest of the app; it lives ONLY in this in-memory object.
    """

    provider: str
    model: str
    api_key: Optional[str] = None

    def require_api_key(self, env_name: str) -> str:
        """Return the API key or raise a clear error if missing."""
        if not self.api_key:
            raise ValueError(
                f"LLM provider '{self.provider}' requires the {env_name} "
                f"environment variable (or .env entry). It was not found."
            )
        return self.api_key


def load_llm_config() -> LLMConfig:
    """Build the active ``LLMConfig`` from environment variables.

    Provider/model defaults come from the caller's expectations; the
    Gemini default model is applied here when ``PSYCHAI_LLM_MODEL`` is unset.
    """
    _load_dotenv_if_available()
    provider = (os.environ.get(PROVIDER_ENV) or "gemini").strip().lower()
    model = os.environ.get(MODEL_ENV)
    if not model:
        model = DEFAULT_GEMINI_MODEL
    api_key = os.environ.get(GEMINI_API_KEY_ENV) or None
    return LLMConfig(provider=provider, model=model, api_key=api_key)
