"""Offline unit tests for the capture module (deterministic PCM logic).

Separate from tests/test_capture.py (the existing standalone live
capture test). This file covers the pure-logic parts with no audio
device, plus one opt-in ``hardware`` test for real device open.
"""

from __future__ import annotations

import struct

import pytest

from capture import CaptureConfig, SystemAudioCapture


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
