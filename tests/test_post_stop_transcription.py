"""Post-stop transcription integration tests (Sprint 11).

Drives Orchestrator.transcribe_session over a real SQLite store with
real Session + AudioTrack rows, but a FAKE transcription backend
(transcribe_file is monkeypatched). No Whisper model is loaded, so the
suite stays fast and offline.

Covers: two tracks -> RAW segments persisted; speaker mapping;
status transitions; empty/partial/failed tracks; idempotent re-run;
refusal when the session is not finished; missing WAV; RAW text
preserved verbatim; and an architecture check (no SQLAlchemy/db leak).
"""

from __future__ import annotations

import os
import wave

import pytest

from db.session_store import SessionStore
from orchestrator.orchestrator import Orchestrator


# ── helpers ────────────────────────────────────────────────────────────

def _make_wav(path: str, rate: int = 44100, seconds: float = 0.2) -> None:
    """Write a tiny valid (silent) mono WAV for the transcriber to open."""
    import numpy as np

    n = int(rate * seconds)
    audio = (np.zeros(n, dtype=np.float32) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(audio.tobytes())


class _FakeBackend:
    """Controllable transcription backend.

    Returns segments keyed by a per-call table; a path containing
    ``__raise__`` raises; a path containing ``__empty__`` returns [].
    """

    def __init__(self, segments_per_call: int = 1):
        self.segments_per_call = segments_per_call

    def __call__(self, path, model_size="small", language=None,
                 device="cpu", compute_type="int8"):
        base = os.path.basename(path)
        if "__raise__" in base:
            raise RuntimeError("simulated transcription failure")
        if "__empty__" in base:
            return []
        segs = []
        for i in range(self.segments_per_call):
            segs.append({
                "start": round(0.0 + i * 1.0, 3),
                "end": round(1.0 + i * 1.0, 3),
                "text": f"seg{i}  Привет  Мир ",  # spaces/case kept RAW
                "confidence": round(-0.1 - i * 0.01, 4),
            })
        return segs


@pytest.fixture
def store_with_session(tmp_path):
    """A store with one COMPLETED session and its two audio tracks.

    Returns (store, session_id, paths dict). Paths point at real tiny
    WAV files (mic / loopback) unless overridden.
    """
    store = SessionStore(str(tmp_path / "live.db"))
    sid = store.create_session(started_at=__import__("datetime").datetime(2026, 1, 1, 12, 0, 0))
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
    store.finalize_session(session_id=sid,
                           ended_at=__import__("datetime").datetime(2026, 1, 1, 12, 0, 5),
                           status="completed")
    return store, sid, {"microphone": mic_path, "loopback": loop_path}


@pytest.fixture
def orch(store_with_session, tmp_path):
    store, sid, _ = store_with_session
    o = Orchestrator(db_path=str(tmp_path / "live.db"))
    o.session.record_id = sid
    o._store = store
    return o


def _segments_in(store, sid):
    from db.database import get_session_factory
    from db.repositories import TranscriptRepository
    with get_session_factory(store._engine)() as db:
        return TranscriptRepository(db).get_by_session(sid)


# ── core flow ──────────────────────────────────────────────────────────

def test_transcribe_writes_segments_for_both_tracks(orch, store_with_session, monkeypatch):
    store, sid, _ = store_with_session
    monkeypatch.setattr("transcription.transcribe_file",
                        _FakeBackend(segments_per_call=2))
    res = orch.transcribe_session()
    assert res["status"] == "transcribed"
    segs = _segments_in(store, sid)
    assert len(segs) == 4  # 2 per track
    by_src = {}
    for s in segs:
        by_src.setdefault(s.speaker, []).append(s)
    assert {s.audio_track_id for s in segs}
    # start/end preserved verbatim
    assert {(round(s.start, 3), round(s.end, 3)) for s in segs} == {
        (0.0, 1.0), (1.0, 2.0)}


def test_speaker_mapping_microphone_psychologist_loopback_client(
        orch, store_with_session, monkeypatch):
    store, sid, _ = store_with_session
    monkeypatch.setattr("transcription.transcribe_file",
                        _FakeBackend(segments_per_call=1))
    orch.transcribe_session()
    segs = _segments_in(store, sid)
    speakers = {s.speaker for s in segs}
    assert speakers == {"psychologist", "client"}


def test_status_completed_to_transcribed(orch, store_with_session, monkeypatch):
    store, sid, _ = store_with_session
    monkeypatch.setattr("transcription.transcribe_file",
                        _FakeBackend(1))
    orch.transcribe_session()
    assert store.get_session_status(sid) == "transcribed"


def test_empty_track_is_not_an_error(orch, store_with_session, monkeypatch, tmp_path):
    """A silent loopback (0 segments) must not fail the session.

    Mirrors the real GUI test where loopback had no system audio.
    """
    store, sid, paths = store_with_session
    # make loopback path resolve to a fake that returns no segments
    empty = str(tmp_path / "loop__empty__.wav")
    open(empty, "w").close()
    # repoint loopback track file_path to the empty-sentinel name
    from db.database import get_session_factory
    from db.repositories import AudioTrackRepository
    with get_session_factory(store._engine)() as db:
        for t in AudioTrackRepository(db).get_by_session(sid):
            if t.source == "loopback":
                t.file_path = empty
                db.commit()
    monkeypatch.setattr("transcription.transcribe_file",
                        _FakeBackend(1))
    res = orch.transcribe_session()
    assert res["status"] == "transcribed"
    segs = _segments_in(store, sid)
    # exactly the mic track's 1 segment
    assert len(segs) == 1
    assert segs[0].speaker == "psychologist"


def test_one_track_error_partial_status(orch, store_with_session, monkeypatch, tmp_path):
    store, sid, paths = store_with_session
    bad = str(tmp_path / "mic__raise__.wav")
    open(bad, "w").close()
    good = paths["loopback"]
    from db.database import get_session_factory
    from db.repositories import AudioTrackRepository
    with get_session_factory(store._engine)() as db:
        for t in AudioTrackRepository(db).get_by_session(sid):
            if t.source == "microphone":
                t.file_path = bad
            else:
                t.file_path = good
            db.commit()
    monkeypatch.setattr("transcription.transcribe_file",
                        _FakeBackend(1))
    res = orch.transcribe_session()
    assert res["status"] == "transcribed_partial"
    segs = _segments_in(store, sid)
    # only loopback (client) survived
    assert len(segs) == 1
    assert segs[0].speaker == "client"
    assert res["tracks"][0]["error"] is not None  # mic error captured
    assert res["tracks"][1]["error"] is None


def test_both_tracks_error_failed_status(orch, store_with_session, monkeypatch, tmp_path):
    store, sid, paths = store_with_session
    bad_mic = str(tmp_path / "mic__raise__.wav")
    bad_loop = str(tmp_path / "loop__raise__.wav")
    open(bad_mic, "w").close()
    open(bad_loop, "w").close()
    from db.database import get_session_factory
    from db.repositories import AudioTrackRepository
    with get_session_factory(store._engine)() as db:
        for t in AudioTrackRepository(db).get_by_session(sid):
            t.file_path = bad_mic if t.source == "microphone" else bad_loop
            db.commit()
    monkeypatch.setattr("transcription.transcribe_file",
                        _FakeBackend(1))
    res = orch.transcribe_session()
    assert res["status"] == "transcription_failed"
    assert _segments_in(store, sid) == []
    # session row intact, not corrupted
    assert store.get_session_status(sid) == "transcription_failed"


def test_rerun_idempotent_no_duplicates(orch, store_with_session, monkeypatch):
    store, sid, _ = store_with_session
    monkeypatch.setattr("transcription.transcribe_file",
                        _FakeBackend(1))
    r1 = orch.transcribe_session()
    assert r1["status"] == "transcribed"
    r2 = orch.transcribe_session()  # re-run
    assert r2["status"] == "transcribed"
    assert all(t["skipped"] == 1 for t in r2["tracks"])
    assert all(t["segments"] == 0 for t in r2["tracks"])
    assert len(_segments_in(store, sid)) == 2  # no duplicates


def test_transcribe_refused_when_not_completed(orch, store_with_session):
    store, sid, _ = store_with_session
    # force status back to "recording"
    store.set_session_status(sid, "recording")
    orch.session.record_id = sid
    res = orch.transcribe_session()
    assert res["status"] == "recording"
    assert res["error"] is not None
    assert _segments_in(store, sid) == []


def test_missing_wav_marked_error_other_survives(orch, store_with_session, monkeypatch, tmp_path):
    store, sid, paths = store_with_session
    missing = str(tmp_path / "does_not_exist_mic.wav")
    from db.database import get_session_factory
    from db.repositories import AudioTrackRepository
    with get_session_factory(store._engine)() as db:
        for t in AudioTrackRepository(db).get_by_session(sid):
            if t.source == "microphone":
                t.file_path = missing
            db.commit()
    monkeypatch.setattr("transcription.transcribe_file",
                        _FakeBackend(1))
    res = orch.transcribe_session()
    assert res["status"] == "transcribed_partial"
    segs = _segments_in(store, sid)
    assert len(segs) == 1
    assert segs[0].speaker == "client"
    mic_track = next(t for t in res["tracks"] if t["source"] == "microphone")
    assert mic_track["error"] == "audio file missing"


def test_raw_text_preserved_verbatim(orch, store_with_session, monkeypatch):
    store, sid, _ = store_with_session
    monkeypatch.setattr("transcription.transcribe_file",
                        _FakeBackend(1))
    orch.transcribe_session()
    segs = _segments_in(store, sid)
    # text (incl. double spaces, mixed case) was stored untouched
    assert all(s.text.startswith("seg") and "  " in s.text for s in segs)


# ── architecture guard ──────────────────────────────────────────────────

def test_transcription_module_does_not_import_app_layers():
    import ast
    import transcription
    import os as _os

    root = _os.path.dirname(transcription.__file__)
    forbidden = {"db", "session", "ui", "orchestrator"}
    for fn in _os.listdir(root):
        if not fn.endswith(".py") or fn == "__init__.py":
            continue
        src = open(_os.path.join(root, fn), encoding="utf-8").read()
        mods = {n.name.split(".")[0] for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.Import)
                for n in [n] if False}
        imported = set()
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Import):
                for a in n.names:
                    imported.add(a.name.split(".")[0])
            elif isinstance(n, ast.ImportFrom) and n.module:
                imported.add(n.module.split(".")[0])
        assert not (imported & forbidden), f"{fn} imports forbidden: {imported & forbidden}"


def test_session_model_still_free_of_sqlalchemy():
    import ast
    import os as _os

    path = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)),
                         "session", "model.py")
    src = open(path, encoding="utf-8").read()
    imported = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            for a in n.names:
                imported.add(a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module.split(".")[0])
    assert not (imported & {"sqlalchemy", "db"}), f"session imports: {imported & {'sqlalchemy', 'db'}}"
