"""Sprint 15 unit test: VAD is disabled for loopback/system audio only.

The transcription backend (faster-whisper) is mocked so no model runs; we
only assert which ``vad_filter`` value ``transcribe_session`` forwards to
``transcribe_file`` per track source. Mirrors the store setup used by the
post-stop transcription tests.
"""
from __future__ import annotations

import os
import wave

from unittest.mock import patch


def _make_wav(path: str, rate: int = 44100, seconds: float = 0.2) -> None:
    import numpy as np

    n = int(rate * seconds)
    audio = (np.zeros(n, dtype=np.float32) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(audio.tobytes())


def _store_with_session(tmp_path):
    from db.session_store import SessionStore

    store = SessionStore(str(tmp_path / "s15.db"))
    sid = store.create_session(started_at=None)
    mic_path = str(tmp_path / "mic.wav")
    loop_path = str(tmp_path / "loopback.wav")
    _make_wav(mic_path, rate=44100)
    _make_wav(loop_path, rate=48000)
    store.add_audio_track(session_id=sid, source="microphone",
                          file_path=mic_path, duration=0.2,
                          sample_rate=44100, channels=1)
    store.add_audio_track(session_id=sid, source="loopback",
                          file_path=loop_path, duration=0.2,
                          sample_rate=48000, channels=1)
    store.finalize_session(session_id=sid, ended_at=None, status="completed")
    return store, sid, {"microphone": mic_path, "loopback": loop_path}


def test_vad_filter_true_for_microphone_false_for_loopback(tmp_path):
    store, sid, _ = _store_with_session(tmp_path)

    calls = []

    def fake_transcribe(path, model_size="small", language=None,
                        device="cpu", compute_type="int8", vad_filter=True,
                        **kwargs):
        calls.append((path, vad_filter))
        return [{"start": 0.0, "end": 1.0, "text": "x", "confidence": 0.0}]

    with patch("transcription.transcribe_file", side_effect=fake_transcribe):
        from orchestrator.orchestrator import Orchestrator

        orch = Orchestrator(db_path=str(tmp_path / "s15.db"))
        orch.session.record_id = sid
        orch._store = store
        res = orch.transcribe_session()

    assert res["status"] == "transcribed"
    tracks = store.get_tracks(sid)
    by_src = {trk["source"]: calls[i][1] for i, trk in enumerate(tracks)}
    assert by_src.get("microphone") is True, \
        f"microphone vad_filter expected True, got {by_src.get('microphone')}"
    assert by_src.get("loopback") is False, \
        f"loopback vad_filter expected False, got {by_src.get('loopback')}"
