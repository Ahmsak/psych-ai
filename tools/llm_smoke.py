"""Sprint 17 developer smoke test for the Gemini analysis provider.

Runs a REAL Gemini call ONLY when GEMINI_API_KEY is present in the
environment (or a .env). Otherwise it prints a clear "skipped" message and
exits without touching the network — never fabricates a key.

Per the sprint rules, a real call uses a SHORT SYNTHETIC transcript only;
no real therapeutic/patient data is ever sent.

Usage:
    python tools/llm_smoke.py
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _synthetic_transcript() -> str:
    """A short, obviously fake transcript — safe to send to a real model."""
    lines = [
        "[0:00.000 -> 0:04.200] (microphone) Здравствуйте, давайте начнём сегодняшнюю сессию.",
        "[0:04.200 -> 0:09.700] (loopback) Здравствуйте. На этой неделе я снова чувствовал тревогу по утрам.",
        "[0:09.700 -> 0:15.100] (microphone) Понимаю. Можете описать, о чём вы думаете в такие моменты?",
        "[0:15.100 -> 0:21.000] (loopback) Я думаю, что всё пойдёт не так, хотя причин нет.",
    ]
    return "\n".join(lines)


def main() -> int:
    from llm.config import GEMINI_API_KEY_ENV, load_llm_config
    from llm.contract import AnalysisRequest
    from llm.prompt import PROMPT_VERSION, build_analysis_prompt
    from llm.provider_factory import get_provider

    config = load_llm_config()
    if not config.api_key:
        print(
            f"[SKIP] {GEMINI_API_KEY_ENV} not set — real Gemini call skipped. "
            f"(provider={config.provider}, model={config.model})"
        )
        return 0

    print(f"[RUN] provider={config.provider} model={config.model} "
          f"prompt_version={PROMPT_VERSION}")
    print("[RUN] using SHORT SYNTHETIC transcript only (no real data).")
    transcript = _synthetic_transcript()
    prompt = build_analysis_prompt(transcript)
    provider = get_provider(config)
    result = provider.analyze(
        AnalysisRequest(prompt=prompt, model=config.model,
                        prompt_version=PROMPT_VERSION))
    print(f"[OK] provider={result.provider} model={result.model} "
          f"prompt_version={result.prompt_version}")
    print("-" * 72)
    print(result.text[:2000])
    if len(result.text) > 2000:
        print("…[truncated]")
    print("-" * 72)
    # Assert the API key never leaked into the result text.
    assert config.api_key not in result.text, "API key leaked into analysis text!"
    print("[OK] API key absent from analysis text.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
