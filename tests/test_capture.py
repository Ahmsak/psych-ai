"""Standalone + pytest-compatible test for the capture module.

WHAT IT DOES
------------
Starts a real WASAPI loopback capture and asserts that PCM chunks are
received. It is intentionally isolated: it imports ONLY ``capture`` and
touches no other project module.

RUN MODES
---------
1. Real (target environment):
       python tests/test_capture.py
   or  pytest tests/test_capture.py
   Requires Windows + ``pyaudiowpatch`` installed. It captures a couple of
   seconds of system audio (silence is still delivered as zeroed PCM frames)
   and asserts non-empty chunks arrive.

2. Headless (this environment, no pyaudiowpatch, no audio device):
       PSYCHAI_FAKE_AUDIO=1 python tests/test_capture.py
   or  PSYCHAI_FAKE_AUDIO=1 pytest tests/test_capture.py
   Injects an in-memory stub of ``pyaudiowpatch`` so the capture logic
   (start -> queue -> iter_chunks) is exercised without the native backend.

If ``pyaudiowpatch`` is missing and PSYCHAI_FAKE_AUDIO is unset, the test
skips cleanly instead of failing.
"""

import os
import sys
import time
import types
import struct

FAKE_ENV = bool(os.environ.get("PSYCHAI_FAKE_AUDIO"))

# ---------------------------------------------------------------------- #
# Optional in-memory stub of pyaudiowpatch (headless verification only).
# ---------------------------------------------------------------------- #
if FAKE_ENV:
    _fake = types.ModuleType("pyaudiowpatch")
    _fake.paWASAPI = 1
    _fake.paInt16 = 8
    _fake.paContinue = 0

    _STATE = {
        "wasapi": True,
        "feed": 3,  # number of chunks pushed on start_stream()
        "stereo": struct.pack("<4h", 100, 200, 300, 400),  # 2 frames stereo
    }

    class _Stream:
        def __init__(self, cb):
            self._cb = cb

        def start_stream(self):
            for _ in range(_STATE["feed"]):
                if self._cb is not None:
                    self._cb(_STATE["stereo"], 512, {}, 0)

        def stop_stream(self):
            pass

        def close(self):
            pass

    class PyAudio:
        def get_host_api_info_by_type(self, _t):
            if not _STATE["wasapi"]:
                raise OSError("WASAPI not available")
            return {"defaultOutputDevice": 0}

        def get_device_info_by_index(self, i):
            if i == 0:
                return {"name": "Speakers", "isLoopbackDevice": False,
                        "index": 0, "defaultSampleRate": 48000.0,
                        "maxInputChannels": 2}
            return {"name": "Speakers (Loopback)", "isLoopbackDevice": True,
                    "index": 1, "defaultSampleRate": 48000.0,
                    "maxInputChannels": 2}

        def get_loopback_device_info_generator(self):
            yield {"name": "Speakers (Loopback)", "isLoopbackDevice": True,
                   "index": 1, "defaultSampleRate": 48000.0,
                   "maxInputChannels": 2}

        def open(self, **kwargs):
            return _Stream(kwargs.get("stream_callback"))

        def terminate(self):
            pass

    _fake.PyAudio = PyAudio
    _fake.STATE = _STATE
    sys.modules["pyaudiowpatch"] = _fake

# ---------------------------------------------------------------------- #
# pytest availability (optional).
# ---------------------------------------------------------------------- #
try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    pytest = None
    HAS_PYTEST = False


# ---------------------------------------------------------------------- #
# Make the project root importable as a package root.
# ---------------------------------------------------------------------- #
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ---------------------------------------------------------------------- #
# Skip logic when the backend is genuinely unavailable.
# ---------------------------------------------------------------------- #
try:
    from capture import CaptureConfig, SystemAudioCapture
except ImportError:
    if FAKE_ENV:
        raise
    _msg = ("SKIP: pyaudiowpatch not available. Install it on Windows, "
            "or run with PSYCHAI_FAKE_AUDIO=1 for a headless check.")
    if HAS_PYTEST:
        pytest.skip(_msg, allow_module_level=True)
    else:
        print(_msg)
        sys.exit(0)

if not FAKE_ENV and sys.platform != "win32":
    _msg = "SKIP: WASAPI loopback requires Windows."
    if HAS_PYTEST:
        pytest.skip(_msg, allow_module_level=True)
    else:
        print(_msg)
        sys.exit(0)


# ---------------------------------------------------------------------- #
# The test.
# ---------------------------------------------------------------------- #
def test_capture_starts_and_yields_pcm_chunks():
    """Start capture (via context manager) and assert PCM chunks arrive,
    then that the session shuts down cleanly."""
    chunks = []
    with SystemAudioCapture(CaptureConfig(mono_mix=True, chunk_size=512)) as cap:
        assert cap.is_running, "capture must be running inside `with`"

        started = time.time()
        for idx, pcm in enumerate(cap.iter_chunks(timeout=1.0), start=1):
            assert isinstance(pcm, (bytes, bytearray)), \
                "each chunk must be raw PCM bytes"
            assert len(pcm) > 0, "each chunk must be non-empty"
            chunks.append(pcm)

            # --- chunk info output ---
            total_bytes = len(pcm)
            sample_count = total_bytes // 2  # int16 = 2 bytes/sample
            channels = cap.output_channels or 1
            frames = sample_count // channels if channels else 0
            preview = struct.unpack(
                "<%dh" % min(sample_count, 6),
                pcm[: min(total_bytes, 12)],
            )
            print(
                "CHUNK #{i}: {b} bytes | {s} samples | {c} ch | "
                "{f} frames | rate={r}Hz | first_samples={p}".format(
                    i=idx, b=total_bytes, s=sample_count, c=channels,
                    f=frames, r=cap.sample_rate, p=preview,
                )
            )

            # In fake mode the backend stops feeding after a fixed count.
            if FAKE_ENV and len(chunks) >= _STATE["feed"]:
                break
            # In real mode, collect for a short window then stop.
            if not FAKE_ENV and time.time() - started > 1.5:
                break

        assert len(chunks) >= 1, "expected at least one PCM chunk"

    # `with` block exited -> stop() must have run automatically.
    assert not cap.is_running, "capture must be stopped after `with` block"
    print("STOPPED: capture released cleanly (%d chunks collected)" % len(chunks))


def test_capture_shuts_down_on_exception():
    """If the consumer raises mid-stream, the context manager must still
    stop the capture and release the device (no leaked audio thread)."""
    cap = SystemAudioCapture(CaptureConfig(mono_mix=True, chunk_size=512))
    try:
        with cap:
            assert cap.is_running
            for _ in cap.iter_chunks(timeout=1.0):
                raise RuntimeError("simulated consumer failure")
    except RuntimeError as exc:
        assert str(exc) == "simulated consumer failure"
    assert not cap.is_running, "capture must stop even when consumer fails"
    print("STOPPED: capture released after in-loop exception")


# ---------------------------------------------------------------------- #
# Direct execution support (no pytest needed).
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    tests = [
        test_capture_starts_and_yields_pcm_chunks,
        test_capture_shuts_down_on_exception,
    ]
    failed = False
    for t in tests:
        try:
            t()
        except Exception as exc:  # noqa: BLE001 - test runner surface
            print("FAIL:", t.__name__, "->", exc)
            failed = True
    if failed:
        sys.exit(1)
    print("PASS: all capture tests")
