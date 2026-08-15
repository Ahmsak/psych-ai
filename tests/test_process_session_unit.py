"""Sprint 14 unit tests: Orchestrator.process_session composition and failure
branches. Mocks the heavy transcribe/build steps so no Whisper/model runs;
what is asserted is the SEQUENCING and STATE TRANSITIONS, not audio quality.
Recovery logic is intentionally ABSENT (removed per audit): a non-transcribed
result (failed / partial / wrong state) is returned unchanged.
"""

from __future__ import annotations

import pytest

from orchestrator.orchestrator import Orchestrator


def _orch():
    # Minimal Orchestrator without a real DB/store.
    return Orchestrator(db_path=":memory:")


def test_process_session_composes_transcribe_then_build(monkeypatch):
    o = _orch()
    calls = []

    def fake_transcribe(sid=None):
        calls.append("transcribe")
        return {"session_id": sid, "status": "transcribed", "tracks": []}

    def fake_build(sid=None):
        calls.append("build")
        return {"session_id": sid, "status": "dialogued", "utterances": 4}

    monkeypatch.setattr(o, "transcribe_session", fake_transcribe)
    monkeypatch.setattr(o, "build_dialogue", fake_build)
    monkeypatch.setattr(o, "_store", None)  # ensure no DB access

    result = o.process_session(1)
    assert calls == ["transcribe", "build"]
    assert result["status"] == "dialogued"
    assert result["utterances"] == 4


def test_process_session_stops_before_build_on_transcription_failed(monkeypatch):
    o = _orch()
    calls = []

    def fake_transcribe(sid=None):
        calls.append("transcribe")
        return {"session_id": sid, "status": "transcription_failed", "tracks": []}

    def fake_build(sid=None):
        calls.append("build")  # must NOT be called
        return {"session_id": sid, "status": "dialogued", "utterances": 0}

    monkeypatch.setattr(o, "transcribe_session", fake_transcribe)
    monkeypatch.setattr(o, "build_dialogue", fake_build)
    monkeypatch.setattr(o, "_store", None)

    result = o.process_session(1)
    assert calls == ["transcribe"]  # build skipped
    assert result["status"] == "transcription_failed"


def test_process_session_propagates_dialogue_failed(monkeypatch):
    o = _orch()
    calls = []

    def fake_transcribe(sid=None):
        calls.append("transcribe")
        return {"session_id": sid, "status": "transcribed", "tracks": []}

    def fake_build(sid=None):
        calls.append("build")
        return {"session_id": sid, "status": "dialogue_failed", "utterances": 0}

    monkeypatch.setattr(o, "transcribe_session", fake_transcribe)
    monkeypatch.setattr(o, "build_dialogue", fake_build)
    monkeypatch.setattr(o, "_store", None)

    result = o.process_session(1)
    assert calls == ["transcribe", "build"]
    assert result["status"] == "dialogue_failed"


def test_process_session_does_not_mutate_status(monkeypatch):
    """No recovery: a failed/partial/transcribing status is returned as-is
    and NOT silently reset to 'completed'."""
    o = _orch()
    seen_statuses = []

    def fake_transcribe(sid=None):
        # Report a non-transcribed state; process_session must return it
        # unchanged without touching the DB status.
        return {"session_id": sid, "status": "transcription_failed", "tracks": []}

    def fake_build(sid=None):
        return {"session_id": sid, "status": "dialogued", "utterances": 4}

    fake_store = type(
        "S", (),
        {"get_session_status": lambda self, sid: "transcription_failed",
         "set_session_status": lambda self, sid, new: seen_statuses.append(new)},
    )()

    monkeypatch.setattr(o, "_store", fake_store)
    monkeypatch.setattr(o, "transcribe_session", fake_transcribe)
    monkeypatch.setattr(o, "build_dialogue", fake_build)

    result = o.process_session(1)
    assert result["status"] == "transcription_failed"
    # The store's set_session_status must never have been called.
    assert seen_statuses == []
