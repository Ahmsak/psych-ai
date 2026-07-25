"""Sprint 5 tests: unified audio format conversion + sensor-first validator.

Offline and deterministic: no audio device, no model download. Imports
the timeline tool and the validator directly and drives them with
synthetic PCM / synthetic experiment directories.
"""

from __future__ import annotations

import json
import os
import sys
import wave

import numpy as np

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "tools")
sys.path.insert(0, TOOLS)

import run_timeline_experiment as tl  # noqa: E402
import check_experiment as chk        # noqa: E402


# ------------------------- unified format ------------------------------ #

def test_to_unified_resamples_to_48k_mono():
    # 1 second of 44100 Hz mono int16 -> ~48000 samples mono
    src = (np.random.randint(-5000, 5000, 44100)
           .astype(np.int16).tobytes())
    out = tl.to_unified(src, 44100, 1)
    n = len(out) // 2
    assert abs(n - 48000) <= 2
    assert len(out) % 2 == 0  # int16


def test_to_unified_downmixes_stereo():
    stereo = np.array([100, 200, -1000, 0], dtype=np.int16).tobytes()
    out = tl.to_unified(stereo, 48000, 2)  # already 48k, only downmix
    vals = np.frombuffer(out, dtype=np.int16)
    assert list(vals) == [150, -500]


def test_to_unified_noop_when_already_unified():
    mono48 = np.array([1, 2, 3, 4], dtype=np.int16).tobytes()
    out = tl.to_unified(mono48, 48000, 1)
    assert np.array_equal(np.frombuffer(out, dtype=np.int16),
                          np.array([1, 2, 3, 4], dtype=np.int16))


# ------------------------- sensor-first validator ---------------------- #

def _write_wav(path, rate=48000, ch=1, width=2, seconds=1):
    wf = wave.open(path, "wb")
    wf.setnchannels(ch)
    wf.setsampwidth(width)
    wf.setframerate(rate)
    wf.writeframes(b"\x01\x01" * (rate * seconds * ch))
    wf.close()


def _good_experiment(base):
    os.makedirs(base, exist_ok=True)
    _write_wav(os.path.join(base, "mic.wav"))
    _write_wav(os.path.join(base, "loopback.wav"))
    for f in ("mic_transcription.txt", "loopback_transcription.txt"):
        with open(os.path.join(base, f), "w", encoding="utf-8") as fh:
            fh.write("hello")
    uf = {"sample_rate": 48000, "channels": 1,
          "sample_width_bytes": 2, "encoding": "pcm_s16le"}
    meta = {
        "session_id": "x", "created_at": "now", "unified_format": uf,
        "microphone": {"wav": "mic.wav", "transcription": "mic_transcription.txt",
                       "rms_max": 500.0, "audio_captured": True},
        "loopback": {"wav": "loopback.wav",
                     "transcription": "loopback_transcription.txt",
                     "rms_max": 500.0, "audio_captured": True},
    }
    with open(os.path.join(base, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f)


def test_validator_passes_on_good_run(tmp_path):
    base = str(tmp_path / "20260101_000000_timeline")
    _good_experiment(base)
    assert chk.validate(base) == 0


def test_validator_fails_without_metadata(tmp_path):
    base = str(tmp_path / "20260101_000001_timeline")
    os.makedirs(base)
    assert chk.validate(base) == 1


def test_validator_fails_on_corrupt_wav(tmp_path):
    base = str(tmp_path / "20260101_000002_timeline")
    _good_experiment(base)
    with open(os.path.join(base, "mic.wav"), "wb") as f:
        f.write(b"not a wav")
    assert chk.validate(base) == 1


def test_validator_fails_on_missing_transcription_with_audio(tmp_path):
    base = str(tmp_path / "20260101_000003_timeline")
    _good_experiment(base)
    os.remove(os.path.join(base, "mic_transcription.txt"))
    assert chk.validate(base) == 1


def test_validator_fails_on_wrong_format(tmp_path):
    base = str(tmp_path / "20260101_000004_timeline")
    _good_experiment(base)
    _write_wav(os.path.join(base, "mic.wav"), rate=16000)  # not unified
    assert chk.validate(base) == 1
