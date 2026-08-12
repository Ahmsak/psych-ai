"""Offline unit tests for the capture module (deterministic PCM logic).

Separate from tests/test_capture.py (the existing standalone live
capture test). This file covers the pure-logic parts with no audio
device, plus one opt-in ``hardware`` test for real device open.
"""

from __future__ import annotations

import ast
import os
import struct

import pytest

from capture import CaptureConfig, SystemAudioCapture
from capture.wav import write_wav

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_downmix_stereo_to_mono_averages():
    # two frames: (100, 200) -> 150 ; (-1000, 0) -> -500
    stereo = struct.pack("<4h", 100, 200, -1000, 0)
    mono = SystemAudioCapture._downmix_mono(stereo)
    vals = struct.unpack("<2h", mono)
    assert vals == (150, -500)


def test_downmix_length_halves():
    stereo = struct.pack("<8h", *range(8))
    mono = SystemAudioCapture._downmix_mono(stereo)
    assert len(mono) == len(stereo) // 2


def test_capture_starts_uninitialised():
    cap = SystemAudioCapture(CaptureConfig())
    assert cap.is_running is False
    assert cap.sample_rate == 0


def test_stop_is_idempotent_before_start():
    """stop() from a finally block must be safe even if never started."""
    cap = SystemAudioCapture(CaptureConfig())
    cap.stop()  # must not raise
    cap.stop()
    assert cap.is_running is False


@pytest.mark.hardware
def test_open_real_loopback_device():
    """Opt-in: open the default WASAPI loopback device and clean up.

    Verifies device open + clean shutdown (no leaked stream). Requires a
    Windows host with a real output device.
    """
    cap = SystemAudioCapture(CaptureConfig(auto_stop_seconds=1.0))
    try:
        cap.start()
        assert cap.is_running is True
        assert cap.sample_rate > 0
        assert cap.output_channels >= 1
    finally:
        cap.stop()
    assert cap.is_running is False


# ── capture/mic.py (extracted from the tools scripts) ─────────────────


def _classes_and_funcs(rel_path: str) -> set[str]:
    with open(os.path.join(_ROOT, rel_path), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef))
    }


def test_tools_have_no_second_microphone_implementation():
    """Both experiment scripts must use capture/mic.py, not their own."""
    for rel in ("tools/run_dual_experiment.py",
                "tools/run_timeline_experiment.py"):
        names = _classes_and_funcs(rel)
        assert "MicRecorder" not in names, rel
        assert "TimedMicRecorder" not in names, rel
        with open(os.path.join(_ROOT, rel), encoding="utf-8") as f:
            src = f.read()
        assert "MicrophoneCapture" in src, f"{rel} must use capture/mic.py"


def test_write_wav_duration_and_file(tmp_path):
    """One WAV writer for both tracks; duration matches the byte count."""
    import wave

    path = str(tmp_path / "a.wav")
    frames = [struct.pack("<2h", 1, 2)] * 4  # 8 frames mono int16
    duration = write_wav(path, frames, 8, 1, ndigits=2)
    assert duration == 1.0
    with wave.open(path, "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getframerate() == 8
        assert wf.getnframes() == 8


@pytest.mark.hardware
def test_microphone_capture_open_and_stop():
    """Opt-in: open the real default microphone and shut it down cleanly."""
    from capture import MicrophoneCapture

    mic = MicrophoneCapture()
    try:
        mic.start()
        assert mic.is_running is True
        assert mic.sample_rate > 0
        assert mic.output_channels == 1
    finally:
        mic.stop()
    assert mic.is_running is False
    mic.stop()  # idempotent
