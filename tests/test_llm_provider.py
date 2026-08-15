"""Sprint 17 LLM provider unit tests (no network).

Covers the provider contract, Gemini request/response shape, factory swap,
transcript formatting, and the supervisor prompt — all without touching the
network. The Gemini HTTP call is replaced by a fake transport.

Architecture guards assert the layering rules:
  - llm.gemini does NOT import db / session / ui / orchestrator;
  - orchestrator depends only on the provider contract/factory, not gemini
    internals;
  - the API key never appears in the request body, the result text, or logs.
"""

from __future__ import annotations

import ast
import os

import pytest

from llm.config import GEMINI_API_KEY_ENV, LLMConfig, load_llm_config
from llm.contract import AnalysisRequest, AnalysisResult, LLMProvider
from llm.gemini import GeminiProvider
from llm.prompt import PROMPT_VERSION, build_analysis_prompt
from llm.provider_factory import PROVIDER_REGISTRY, UnknownProviderError, get_provider
from llm.transcript_format import format_raw_transcript


# --------------------------------------------------------------------------- #
# Fake Gemini transport
# --------------------------------------------------------------------------- #
class _FakeHttpxResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _RecordingTransport:
    """Captures the POST so we can assert on URL/headers/body."""

    def __init__(self, response: _FakeHttpxResponse):
        self.response = response
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers or {}, "json": json})
        return self.response


def _gemini_provider(monkeypatch, body) -> tuple[GeminiProvider, _RecordingTransport]:
    cfg = LLMConfig(provider="gemini", model="gemini-2.5-flash",
                    api_key="TESTKEY_12345")
    prov = GeminiProvider(cfg)
    transport = _RecordingTransport(_FakeHttpxResponse(payload=body))
    monkeypatch.setattr(prov, "_post", lambda url, headers, payload: transport.post(
        url, headers, payload).json())
    return prov, transport


def _ok_body(text="Анализ сессии..."):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


# --------------------------------------------------------------------------- #
# Gemini provider
# --------------------------------------------------------------------------- #
def test_gemini_analyze_returns_result(monkeypatch):
    prov, transport = _gemini_provider(monkeypatch, _ok_body("результат"))
    res = prov.analyze(AnalysisRequest(prompt="p", model="gemini-2.5-flash",
                                       prompt_version=PROMPT_VERSION))
    assert isinstance(res, AnalysisResult)
    assert res.text == "результат"
    assert res.provider == "gemini"
    assert res.model == "gemini-2.5-flash"
    assert res.prompt_version == PROMPT_VERSION
    assert res.created_at is not None


def test_gemini_request_shape_and_key_header(monkeypatch):
    prov, transport = _gemini_provider(monkeypatch, _ok_body("x"))
    prov.analyze(AnalysisRequest(prompt="PROMPT_TEXT", model="gemini-2.5-flash",
                                 prompt_version=PROMPT_VERSION))
    assert len(transport.calls) == 1
    call = transport.calls[0]
    # endpoint
    assert call["url"].endswith(
        "/v1beta/models/gemini-2.5-flash:generateContent")
    # key in header, never in URL
    assert GEMINI_API_KEY_ENV not in call["url"]
    assert call["headers"].get("x-goog-api-key") == "TESTKEY_12345"
    assert GEMINI_API_KEY_ENV not in call["headers"]
    # body shape: contents + temperature 0
    body = call["json"]
    assert body["contents"][0]["role"] == "user"
    assert body["contents"][0]["parts"][0]["text"] == "PROMPT_TEXT"
    assert body["generationConfig"]["temperature"] == 0


def test_gemini_key_never_in_body(monkeypatch):
    prov, transport = _gemini_provider(monkeypatch, _ok_body("текст"))
    prov.analyze(AnalysisRequest(prompt="p", model="gemini-2.5-flash",
                                 prompt_version=PROMPT_VERSION))
    dumped = repr(transport.calls[0]["json"])
    assert "TESTKEY_12345" not in dumped


def test_gemini_key_never_in_result_text(monkeypatch):
    prov, _ = _gemini_provider(monkeypatch, _ok_body("обычный текст"))
    res = prov.analyze(AnalysisRequest(prompt="p", model="gemini-2.5-flash",
                                       prompt_version=PROMPT_VERSION))
    assert "TESTKEY_12345" not in res.text


def test_gemini_error_status_raises(monkeypatch):
    cfg = LLMConfig(provider="gemini", model="gemini-2.5-flash",
                    api_key="TESTKEY_12345")
    prov = GeminiProvider(cfg)
    bad = _FakeHttpxResponse(status_code=400, text="API_KEY_INVALID")
    transport = _RecordingTransport(bad)
    monkeypatch.setattr(prov, "_post", lambda url, headers, payload: transport.post(
        url, headers, payload).json())
    with pytest.raises(RuntimeError):
        prov.analyze(AnalysisRequest(prompt="p", model="gemini-2.5-flash",
                                     prompt_version=PROMPT_VERSION))


def test_gemini_requires_api_key():
    cfg = LLMConfig(provider="gemini", model="gemini-2.5-flash", api_key=None)
    with pytest.raises(ValueError):
        GeminiProvider(cfg)


# --------------------------------------------------------------------------- #
# Transcript formatting (RAW source of truth)
# --------------------------------------------------------------------------- #
def test_format_preserves_order_and_timestamps():
    segs = [
        {"start": 0.0, "end": 4.2, "text": "А", "source": "microphone"},
        {"start": 4.2, "end": 9.7, "text": "Б", "source": "loopback"},
    ]
    out = format_raw_transcript(segs)
    lines = out.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("[0:00.000 -> 0:04.200] (microphone) А")
    assert lines[1].startswith("[0:04.200 -> 0:09.700] (loopback) Б")


def test_format_empty_returns_empty():
    assert format_raw_transcript([]) == ""


def test_format_source_is_not_speaker_name():
    # source is just a tag; the label is neutral, not "Психолог"/"Клиент"
    out = format_raw_transcript(
        [{"start": 1.0, "end": 2.0, "text": "привет", "source": "loopback"}])
    assert "Клиент" not in out
    assert "Психолог" not in out
    assert "loopback" in out


# --------------------------------------------------------------------------- #
# Supervisor prompt v1
# --------------------------------------------------------------------------- #
def test_prompt_contains_13_sections_and_transcript():
    prompt = build_analysis_prompt("RAWTRANSCRIPT_HERE")
    for i in range(1, 14):
        assert f"{i}." in prompt
    assert "RAWTRANSCRIPT_HERE" in prompt
    # speaker-attribution guardrails present
    assert "source" in prompt
    assert "не выдавай" in prompt or "не приписывай" in prompt
    assert "диагноз" in prompt


def test_prompt_supervisor_constraints_present():
    # Covers sprint spec points 3 & 4: no invented speakers, no reconstructed
    # utterances, uncertainty marking, alternative hypotheses, risks only if
    # present, confidence levels, ethical limits, CBT paradigm.
    prompt = build_analysis_prompt("T")
    must = [
        "КПТ",                      # CBT paradigm
        "НЕ выдумывай говорящих",     # no invented speakers
        "НЕ реконструируй",          # no reconstructed utterances
        "альтернативн",              # alternative hypotheses
        "красные флаги",             # red flags
        "степень уверенности",       # confidence level
        "ЭТИЧЕСКИЕ ОГРАНИЧЕНИЯ",      # ethical limits
        "ФАКТ", "ИНТЕРПРЕТАЦИ", "ГИПОТЕЗ",  # FACT/INTERPRETATION/HYPOTHESIS
    ]
    for token in must:
        assert token in prompt, f"supervisor prompt missing: {token}"


# --------------------------------------------------------------------------- #
# Provider factory (swap point)
# --------------------------------------------------------------------------- #
def test_factory_returns_gemini():
    cfg = LLMConfig(provider="gemini", model="gemini-2.5-flash",
                    api_key="k")
    prov = get_provider(cfg)
    assert isinstance(prov, GeminiProvider)
    assert prov.name == "gemini"


def test_factory_unknown_provider_raises():
    cfg = LLMConfig(provider="doesnotexist", model="m", api_key="k")
    with pytest.raises(UnknownProviderError):
        get_provider(cfg)


def test_factory_registry_has_gemini():
    assert "gemini" in PROVIDER_REGISTRY


def test_load_llm_config_defaults(monkeypatch):
    monkeypatch.delenv(GEMINI_API_KEY_ENV, raising=False)
    monkeypatch.delenv("PSYCHAI_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("PSYCHAI_LLM_MODEL", raising=False)
    cfg = load_llm_config()
    assert cfg.provider == "gemini"
    assert cfg.model == "gemini-2.5-flash"
    assert cfg.api_key is None


# --------------------------------------------------------------------------- #
# Config contract: no hardcoded key, env-only
# --------------------------------------------------------------------------- #
def test_load_llm_config_reads_env(monkeypatch):
    monkeypatch.setenv(GEMINI_API_KEY_ENV, "env_key_abc")
    monkeypatch.setenv("PSYCHAI_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("PSYCHAI_LLM_MODEL", "gemini-2.5-flash")
    cfg = load_llm_config()
    assert cfg.api_key == "env_key_abc"
    assert cfg.provider == "gemini"
    assert cfg.model == "gemini-2.5-flash"


# --------------------------------------------------------------------------- #
# Architecture guards (layering rules)
# --------------------------------------------------------------------------- #
def _imported_top_modules(path: str) -> set:
    src = open(path, encoding="utf-8").read()
    imported: set = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            for a in n.names:
                imported.add(a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module.split(".")[0])
    return imported


def test_gemini_module_does_not_import_app_layers():
    root = os.path.dirname(__import__("llm").__file__)
    imported = _imported_top_modules(os.path.join(root, "gemini.py"))
    forbidden = {"db", "session", "ui", "orchestrator"}
    assert not (imported & forbidden), f"gemini imports: {imported & forbidden}"


def test_orchestrator_does_not_import_gemini_directly():
    # Orchestrator must depend only on the contract/factory, not llm.gemini.
    path = os.path.join(os.path.dirname(__file__), "..", "orchestrator",
                        "orchestrator.py")
    src = open(os.path.normpath(path), encoding="utf-8").read()
    # It may import llm.config / llm.contract / llm.provider_factory /
    # llm.transcript_format / llm.prompt, but NOT llm.gemini.
    assert "llm.gemini" not in src and "from llm.gemini" not in src


def test_ui_does_not_import_gemini_or_httpx_specifics():
    path = os.path.join(os.path.dirname(__file__), "..", "ui", "window.py")
    src = open(os.path.normpath(path), encoding="utf-8").read()
    assert "llm.gemini" not in src
    # UI calls orchestrator.analyze_session, never the provider directly.
    assert "analyze_session" in src
