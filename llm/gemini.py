"""Gemini provider adapter (the ONLY place that knows Gemini specifics).

Uses the Gemini REST API directly via ``httpx`` (already a project
dependency — no new package needed). The API key is sent in the
``x-goog-api-key`` header and is NEVER placed in the URL, the request body,
the database, or any log line.

All Gemini-specific details (base URL, endpoint path, request/response
shape) live here. The Orchestrator talks only to the ``LLMProvider``
contract + ``provider_factory``, so swapping Gemini for another backend
requires NO changes outside this package.

Network I/O is isolated in ``_post`` so the rest of the class is trivially
testable with a monkeypatched transport.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from llm.config import GEMINI_API_KEY_ENV, LLMConfig
from llm.contract import AnalysisRequest, AnalysisResult, LLMProvider

# Non-secret: the public Gemini REST endpoint host/path. The key is NOT here.
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_GENERATE_PATH = "/models/{model}:generateContent"

# Deterministic analysis: no sampling randomness.
SAMPLING_TEMPERATURE = 0.0

# Cap the response so a runaway model cannot blow up storage/logs.
MAX_OUTPUT_CHARS = 32000


class GeminiProvider(LLMProvider):
    """Gemini backend for ``LLMProvider.analyze``."""

    name = "gemini"

    def __init__(self, config: LLMConfig, *, timeout_s: float = 120.0) -> None:
        # require_api_key validates presence; the key itself stays in config only.
        self._api_key = config.require_api_key(GEMINI_API_KEY_ENV)
        self._model = config.model
        self._timeout = timeout_s

    # -- public contract -------------------------------------------------- #

    def analyze(self, request: AnalysisRequest) -> AnalysisResult:
        url = (
            f"{GEMINI_API_BASE}"
            f"{GEMINI_GENERATE_PATH.format(model=self._model)}"
        )
        headers = {
            "x-goog-api-key": self._api_key,  # key in header, never in URL/body
            "Content-Type": "application/json",
        }
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": request.prompt}],
                }
            ],
            "generationConfig": {
                "temperature": SAMPLING_TEMPERATURE,
                # Keep the model focused on the analysis text.
                "maxOutputTokens": MAX_OUTPUT_CHARS,
            },
        }
        body = self._post(url, headers, payload)
        text = self._extract_text(body)
        return AnalysisResult(
            text=text,
            provider=self.name,
            model=self._model,
            prompt_version=request.prompt_version,
            raw=self._redact_for_debug(body),
        )

    # -- transport (isolated for testing) --------------------------------- #

    def _post(self, url: str, headers: dict, payload: dict) -> dict:
        """Perform the HTTP POST and return the parsed JSON response."""
        import httpx

        resp = httpx.post(
            url, headers=headers, json=payload, timeout=self._timeout
        )
        if resp.status_code != 200:
            # Include the status and a short error snippet; never echo the key.
            snippet = (resp.text or "")[:500]
            raise RuntimeError(
                f"Gemini API error {resp.status_code}: {snippet}"
            )
        return resp.json()

    # -- parsing ---------------------------------------------------------- #

    @staticmethod
    def _extract_text(body: dict) -> str:
        """Pull the generated text out of a Gemini generateContent response.

        Response shape (simplified):
            {"candidates":[{"content":{"parts":[{"text":"..."}]}}]}
        """
        candidates = body.get("candidates") or []
        if not candidates:
            # Some error/blocked cases omit candidates; surface the reason.
            raise RuntimeError(
                "Gemini returned no candidates (possibly blocked). "
                f"fullResponse={json.dumps(body)[:500]}"
            )
        parts = (
            (candidates[0].get("content") or {}).get("parts") or []
        )
        text = "".join(p.get("text", "") for p in parts).strip()
        if not text:
            raise RuntimeError(
                "Gemini returned an empty analysis text. "
                f"fullResponse={json.dumps(body)[:500]}"
            )
        return text

    @staticmethod
    def _redact_for_debug(body: dict) -> Optional[dict]:
        """Return a debug copy of the response WITHOUT any key material.

        The Gemini response never contains the API key, but we keep this
        explicit so a future field addition cannot accidentally persist it.
        """
        if not isinstance(body, dict):
            return None
        return {k: v for k, v in body.items() if k not in ("key", "apiKey")}
