"""Sprint 10 tests: integration harness (engineering tool).

Offline and deterministic: builds a synthetic experiment dir with valid
artifacts, runs each stage, and asserts PASS + that artifacts are NOT
modified. Also checks a broken dir yields FAIL.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import run_integration_validation as riv
from run_integration_validation import (PASS, WARNING, FAIL, run_report,
                                        stage_metadata, stage_session)


def _write_wav(path, seconds=1, rate=48000):
    import wave
    import struct
    wf = wave.open(path, "wb")
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(rate)
    wf.writeframes(struct.pack("<" + "h" * rate, *([1000] * rate)) * seconds)
    wf.close()


def _unified():
    return {"sample_rate": 48000, "channels": 1, "sample_width_bytes": 2,
            "encoding": "pcm_s16le"}


def _metadata():
    return {
        "session_id": "s1",
        "created_at": "2026-01-01T00:00:00",
        "unified_format": _unified(),
        "microphone": {
            "role": "outgoing", "device": "mic", "native_sample_rate": 44100,
            "native_channels": 1, "stored_format": _unified(),
            "record_start": "2026-01-01T00:00:00",
            "first_frame_at": "2026-01-01T00:00:00.100",
            "duration_sec": 1.0, "rms_max": 1000.0, "audio_captured": True,
            "wav": "mic.wav", "transcription": "mic_transcription.txt",
            "segments": "mic_segments.json", "errors": [],
        },
        "loopback": {
            "role": "incoming", "device": "spk", "native_sample_rate": 48000,
            "native_channels": 2, "stored_format": _unified(),
            "record_start": "2026-01-01T00:00:00",
            "first_frame_at": "2026-01-01T00:00:00.200",
            "duration_sec": 1.0, "rms_max": 1000.0, "audio_captured": True,
            "wav": "loopback.wav", "transcription": "loopback_transcription.txt",
            "segments": "loopback_segments.json", "errors": [],
        },
    }


def _build_experiment(base):
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(_metadata(), f)
    _write_wav(os.path.join(base, "mic.wav"))
    _write_wav(os.path.join(base, "loopback.wav"))
    for who, txt in (("mic", "Здравствуйте как дела"),
                     ("loopback", "Всё хорошо спасибо")):
        with open(os.path.join(base, f"{who}_transcription.txt"), "w",
                  encoding="utf-8") as f:
            f.write(txt)
    mic_seg = [{"start": 0.0, "end": 0.9, "text": "Здравствуйте как дела",
                "confidence": -0.2}]
    loop_seg = [{"start": 0.0, "end": 0.9, "text": "Всё хорошо спасибо",
                 "confidence": -0.1}]
    with open(os.path.join(base, "mic_segments.json"), "w",
              encoding="utf-8") as f:
        json.dump(mic_seg, f)
    with open(os.path.join(base, "loopback_segments.json"), "w",
              encoding="utf-8") as f:
        json.dump(loop_seg, f)


def _dir_fingerprint(base):
    fp = {}
    for name in sorted(os.listdir(base)):
        p = os.path.join(base, name)
        if os.path.isfile(p):
            fp[name] = hashlib.md5(open(p, "rb").read()).hexdigest()
    return fp


def test_report_pass_and_no_artifact_mutation(tmp_path, capsys):
    base = str(tmp_path / "20260101_000000_timeline")
    _build_experiment(base)
    before = _dir_fingerprint(base)
    before_files = set(os.listdir(base))

    rc = run_report(base)
    out = capsys.readouterr().out

    assert rc == 0
    assert "Overall Result: PASS" in out
    assert "Audio Capture" in out and "Orchestrator" in out
    # Harness must NOT modify existing artifacts...
    after = _dir_fingerprint(base)
    for name, h in before.items():
        assert after.get(name) == h, f"{name} was modified"
    # ...but may build timeline.json/conversation.json on demand (new files
    # are acceptable; existing artifacts must be untouched).
    assert before_files.issubset(set(os.listdir(base)))


def test_metadata_stage_fail_on_missing():
    r = stage_metadata("/nonexistent", None)
    assert r.status == FAIL


def test_report_fail_on_empty_dir(tmp_path, capsys):
    base = str(tmp_path / "20260101_000001_timeline")
    os.makedirs(base)
    rc = run_report(base)
    out = capsys.readouterr().out
    assert rc == 1
    assert "Overall Result: FAIL" in out


def test_session_stage_uses_temp_file_not_artifact(tmp_path):
    base = str(tmp_path / "20260101_000002_timeline")
    _build_experiment(base)
    stage_session(base)
    # serialization round-trip must go to temp, not create session.json here
    assert not os.path.exists(os.path.join(base, "session.json"))
