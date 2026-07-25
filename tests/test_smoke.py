"""Smoke tests: modules import and public config objects behave.

Fast, offline, no audio device, no model download. Catches the most
common regressions (broken imports, config wiring) in under a second.
"""

from __future__ import annotations


def test_import_capture():
    import capture
    assert hasattr(capture, "SystemAudioCapture")
    assert hasattr(capture, "CaptureConfig")


def test_import_transcription():
    import transcription
    assert hasattr(transcription, "StreamingTranscriber")
    assert hasattr(transcription, "TranscriptionConfig")


def test_import_orchestrator():
    import orchestrator  # noqa: F401


def test_capture_config_defaults():
    from capture import CaptureConfig
    cfg = CaptureConfig()
    assert cfg.chunk_size > 0
    assert cfg.mono_mix is True
    assert cfg.process_id is None


def test_transcription_config_is_tunable():
    from transcription import TranscriptionConfig
    cfg = TranscriptionConfig(window_duration_sec=10.0, language="ru")
    assert cfg.window_duration_sec == 10.0
    assert cfg.language == "ru"
    # window duration is a parameter, not hard-coded
    assert TranscriptionConfig().window_duration_sec > 0


def test_process_loopback_not_implemented():
    """process_id is a documented future extension that must fail loudly."""
    import pytest
    from capture import CaptureConfig, SystemAudioCapture
    with pytest.raises(NotImplementedError):
        SystemAudioCapture(CaptureConfig(process_id=1234))
