"""Sprint 6 tests: timeline build, consistency checks, session API.

Offline and deterministic: synthetic metadata dicts and temp dirs, no
audio device, no model. Drives build_timeline + session_manager directly.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "tools")
sys.path.insert(0, TOOLS)

import build_timeline as bt          # noqa: E402
import session_manager as sm         # noqa: E402


UF = {"sample_rate": 48000, "channels": 1,
      "sample_width_bytes": 2, "encoding": "pcm_s16le"}


def _meta():
    return {
        "session_id": "s1",
        "created_at": "2026-01-01T00:00:00",
        "unified_format": UF,
        "microphone": {
            "role": "outgoing", "wav": "mic.wav",
            "transcription": "mic_transcription.txt", "stored_format": UF,
            "record_start": "2026-01-01T00:00:00.000000",
            "first_frame_at": "2026-01-01T00:00:00.200000",
            "duration_sec": 10.0, "audio_captured": True,
        },
        "loopback": {
            "role": "incoming", "wav": "loopback.wav",
            "transcription": "loopback_transcription.txt", "stored_format": UF,
            "record_start": "2026-01-01T00:00:00.500000",
            "first_frame_at": "2026-01-01T00:00:01.000000",
            "duration_sec": 9.0, "audio_captured": True,
        },
    }


# --------------------------- build_timeline ---------------------------- #

def test_build_computes_start_end_and_offsets():
    tl = bt.build_timeline(_meta())
    # timeline_start = min record_start = mic's 00:00.000
    assert tl["timeline_start"].endswith("00:00:00")
    # offsets: mic first_frame 0.2s after start; loopback 1.0s after start
    off = tl["offsets"]["per_track_sec"]
    assert off["microphone"] == pytest.approx(0.2, abs=1e-3)
    assert off["loopback"] == pytest.approx(1.0, abs=1e-3)
    assert tl["offsets"]["loopback_minus_mic_sec"] == pytest.approx(0.8, abs=1e-3)


def test_build_fails_when_offset_undeterminable():
    m = _meta()
    m["loopback"]["first_frame_at"] = None
    with pytest.raises(ValueError):
        bt.build_timeline(m)


# --------------------------- consistency checks ------------------------ #

def test_validate_passes_on_consistent_timeline():
    m = _meta()
    assert bt.validate_timeline(bt.build_timeline(m), m) == []


def test_validate_fails_on_session_id_mismatch():
    m = _meta()
    tl = bt.build_timeline(m)
    tl["session_id"] = "other"
    assert any("session_id" in f for f in bt.validate_timeline(tl, m))


def test_validate_fails_on_incompatible_format():
    m = _meta()
    tl = bt.build_timeline(m)
    tl["tracks"]["loopback"]["stored_format"] = {"sample_rate": 16000}
    assert any("incompatible" in f or "stored_format" in f
               for f in bt.validate_timeline(tl, m))


def test_validate_fails_on_missing_key_corrupt():
    m = _meta()
    tl = bt.build_timeline(m)
    del tl["offsets"]
    assert any("offsets" in f for f in bt.validate_timeline(tl, m))


# --------------------------- session API ------------------------------- #

def _write_experiment(base, meta):
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f)
    for t in ("mic", "loopback"):
        with open(os.path.join(base, f"{t}_transcription.txt"), "w",
                  encoding="utf-8") as f:
            f.write(f"{t} text")
        open(os.path.join(base, f"{t}.wav"), "wb").close()


def test_load_session_builds_and_exposes_accessors(tmp_path):
    base = str(tmp_path / "20260101_000000_timeline")
    _write_experiment(base, _meta())
    s = sm.load_session(base)
    assert s.session_id == "s1"
    assert s.track_names() == ["microphone", "loopback"]
    assert s.offset_of("loopback") == pytest.approx(1.0, abs=1e-3)
    assert s.wav_path("microphone").endswith("mic.wav")
    assert s.transcription_text("loopback") == "loopback text"
    # built in-memory from metadata; loader has no write side effects
    assert s.timeline_start.endswith("00:00:00")


def test_load_timeline_missing_inputs_raises(tmp_path):
    base = str(tmp_path / "20260101_000001_timeline")
    os.makedirs(base)
    with pytest.raises(FileNotFoundError):
        sm.load_timeline(base)
