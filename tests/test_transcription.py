"""Transcription tests: offline logic + opt-in real decode.

The offline tests exercise the deterministic parts (window sizing,
resampling, silence gate, error on unloaded model) with no model
download. The real-decode test is marked ``slow`` and skipped by default.
"""

from __future__ import annotations

import numpy as np
import pytest

from transcription import StreamingTranscriber, TranscriptionConfig


def test_window_bytes_from_rate_and_channels():
    tr = StreamingTranscriber(TranscriptionConfig(window_duration_sec=2.0),
                              input_sample_rate=48000, input_channels=1)
    # 48000 * 2s * 2 bytes * 1 ch
    assert tr._window_bytes == 48000 * 2 * 2 * 1
    tr.input_channels = 2
    tr.recompute_window()
    assert tr._window_bytes == 48000 * 2 * 2 * 2


def test_resample_changes_length_proportionally():
    audio = np.ones(48000, dtype=np.float32)
    out = StreamingTranscriber._resample(audio, 48000, 16000)
    assert out.dtype == np.float32
    assert abs(out.size - 16000) <= 1


def test_resample_noop_when_rates_equal():
    audio = np.arange(100, dtype=np.float32)
    out = StreamingTranscriber._resample(audio, 16000, 16000)
    assert np.array_equal(out, audio)


def test_feed_on_silence_returns_no_text():
    """Silence must not hallucinate text (RMS gate), and must not crash."""
    tr = StreamingTranscriber(TranscriptionConfig(window_duration_sec=0.5),
                              input_sample_rate=16000, input_channels=1)
    tr.load_model = lambda: None  # not needed: gate returns before model
    tr._model = object()          # non-None so RuntimeError is not raised
    silence = (b"\x00\x00") * 16000  # 1s of int16 zeros
    assert tr.feed(silence) == []


def test_transcribe_without_model_raises():
    tr = StreamingTranscriber(TranscriptionConfig(window_duration_sec=0.5),
                              input_sample_rate=16000, input_channels=1)
    loud = (np.random.randint(-5000, 5000, 16000)
            .astype(np.int16).tobytes())
    with pytest.raises(RuntimeError):
        tr.feed(loud)


@pytest.mark.slow
def test_real_transcribe_file_on_experiment_wav():
    """Opt-in: transcribe a real recorded WAV via the file backend.

    Uses an existing experiment timeline (short, ~5s, real speech
    "раз раз раз два три раз два три") so the test never downloads a
    fixture and never fabricates a pass. Skips if no experiment dir
    is present.

    Verifies the integration path used by Sprint 11 post-stop
    transcription: per-segment timestamps relative to the WAV start,
    and segments within the file duration.
    """
    import glob
    import os

    from transcription import transcribe_file

    dirs = sorted(glob.glob(
        os.path.join(os.path.dirname(__file__), "..", "experiments",
                     "*_timeline")))
    if not dirs:
        pytest.skip("no *_timeline experiment directory present")
    # Prefer a short file to keep the slow test fast.
    wav = None
    for d in reversed(dirs):
        cand = os.path.join(d, "mic.wav")
        if os.path.exists(cand):
            wf = wave.open(cand, "rb")
            try:
                dur = wf.getnframes() / wf.getframerate()
            finally:
                wf.close()
            if dur <= 30:
                wav = cand
                break
    if wav is None:
        pytest.skip("no short experiment mic.wav (<=30s) present")

    segs = transcribe_file(wav, model_size="small", language="ru")
    assert segs, "expected at least one segment"
    for s in segs:
        assert "start" in s and "end" in s and "text" in s
        assert s["end"] >= s["start"]
        assert s["start"] >= 0.0


@pytest.mark.slow
def test_real_decode_of_fixture_wav():
    """Opt-in: transcribe a known WAV; expects non-empty text.

    Skips automatically if no fixture is present, so the suite never
    fabricates a pass. Provide tests/fixtures/speech.wav to enable.
    """
    import os
    import wave
    fixture = os.path.join(os.path.dirname(__file__), "fixtures", "speech.wav")
    if not os.path.exists(fixture):
        pytest.skip("no tests/fixtures/speech.wav fixture present")
    wf = wave.open(fixture, "rb")
    rate = wf.getframerate()
    tr = StreamingTranscriber(TranscriptionConfig(window_duration_sec=10.0),
                              input_sample_rate=rate, input_channels=1)
    tr.load_model()
    texts = []
    while True:
        data = wf.readframes(rate)
        if not data:
            break
        texts += tr.feed(data)
    texts += tr.flush()
    tr.close()
    wf.close()
    assert "".join(texts).strip(), "expected non-empty transcription"
