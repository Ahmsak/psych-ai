"""LLM analysis package for PsychAI (Sprint 17).

Public surface used by the Orchestrator and tools:
  - LLMProvider, AnalysisRequest, AnalysisResult (contract)
  - load_llm_config, LLMConfig (config)
  - get_provider (provider factory / swap point)
  - build_analysis_prompt, PROMPT_VERSION (supervisor prompt v1)
  - format_raw_transcript (RAW transcript -> prompt text)

Gemini-specific code is isolated in ``llm.gemini``; nothing else imports it
directly.
"""

from llm.config import LLMConfig, load_llm_config
from llm.contract import AnalysisRequest, AnalysisResult, LLMProvider
from llm.prompt import PROMPT_VERSION, SUPERVISOR_PROMPT_V1, build_analysis_prompt
from llm.provider_factory import UnknownProviderError, get_provider
from llm.transcript_format import format_raw_transcript

__all__ = [
    "LLMConfig",
    "load_llm_config",
    "LLMProvider",
    "AnalysisRequest",
    "AnalysisResult",
    "get_provider",
    "UnknownProviderError",
    "PROMPT_VERSION",
    "SUPERVISOR_PROMPT_V1",
    "build_analysis_prompt",
    "format_raw_transcript",
]
