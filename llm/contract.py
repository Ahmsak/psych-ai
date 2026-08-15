"""LLM analysis provider contract (provider-independent core).

Defines the internal contract that the Orchestrator and UI depend on.
No network, no Gemini, no SQLAlchemy here — just the shape of the data
and the abstract provider every backend (Gemini, future Alem/DeepSeek/Kimi/
OpenAI) must satisfy.

The Orchestrator calls ``provider.analyze(request)`` and gets back an
``AnalysisResult``. It never sees HTTP, SDK, or provider-specific URLs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AnalysisRequest:
    """What the Orchestrator hands to a provider.

    ``prompt`` already contains the formatted RAW transcript + supervisor
    instructions (built by ``llm.prompt``). ``model`` and ``prompt_version``
    are recorded on the result so the analysis is reproducible/auditable.
    """

    prompt: str
    model: str
    prompt_version: str


@dataclass
class AnalysisResult:
    """Provider-agnostic analysis output.

    ``text`` is the model's analysis (markdown/plain text). ``provider``,
    ``model``, ``prompt_version`` and ``created_at`` are metadata persisted
    alongside the text so a future reader knows exactly how the result was
    produced. ``raw`` optionally keeps the provider's original payload for
    debugging (NEVER the API key).
    """

    text: str
    provider: str
    model: str
    prompt_version: str
    created_at: datetime = field(default_factory=_utcnow)
    raw: Optional[dict] = None


class LLMProvider(ABC):
    """Single contract every analysis backend must satisfy.

    Subclasses implement ``analyze`` only. The name is a stable identifier
    (e.g. ``"gemini"``) recorded on the persisted result.
    """

    name: str = "base"

    @abstractmethod
    def analyze(self, request: AnalysisRequest) -> AnalysisResult:
        """Run the analysis and return an ``AnalysisResult``."""
        raise NotImplementedError
