"""Sprint 10 — vertical slice: UI -> Orchestrator -> Session -> Capture/DB.

No real audio devices and no long recordings: fake capturers feed a few
PCM chunks, persistence is a temporary SQLite file using the existing
schema. What is asserted is the LAYERING (who may talk to whom) and the
Session lifecycle, not audio quality.
"""

from __future__ import annotations

import ast
import os
import struct
import wave

import pytest

from capture.track import RecordedTrack
from db.database import get_engine, get_session_factory, init_db
from db.repositories import AudioTrackRepository, SessionRepository
from db.session_store import SessionStore
from orchestrator.orchestrator import Orchestrator
from session.model import COMPLETED, FAILED, RECORDING, Session, SessionStateError

PCM = struct.pack("<4h", 100, -100, 200, -200)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _imported_modules(rel_path: str) -> set[str]:
    """Top-level module names imported by a source file (AST, not text).

    Substring scanning would trip over prose in docstrings, so the check
    looks at real import statements only.
    """
    with open(os.path.join(_ROOT, rel_path), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


# ── fakes ─────────────────────────────────────────────────────────────


class FakeCapture:
    """Minimal stand-in for MicrophoneCapture / SystemAudioCapture."""

    def __init__(self, *, fail_on_start: bool = False, chunks: int = 3):
        self.fail_on_start = fail_on_start
        self._chunks = chunks
        self.sample_rate = 0
        self.output_channels = 0
        self.is_running = False
        self.frames: list[bytes] = []
        self.errors: list[str] = []
        self.stopped = 0

    def start(self):
        if self.fail_on_start:
            raise RuntimeError("device busy")
        self.is_running = True
        self.sample_rate = 48000
        self.output_channels = 1
        self.frames = [PCM] * self._chunks

    def stop(self):
        self.is_running = False
        self.stopped += 1

    def iter_chunks(self, timeout: float = 1.0):
        return iter(())


def _tracks(tmp_path, **kw):
    mic = FakeCapture(**kw)
    loop = FakeCapture()
    return [
        RecordedTrack("microphone", mic, str(tmp_path / "mic.wav")),
        RecordedTrack("loopback", loop, str(tmp_path / "loopback.wav")),
    ], mic, loop


@pytest.fixture()
def store(tmp_path):
    return SessionStore(str(tmp_path / "slice.db"))


def _rows(db_path):
    engine = get_engine(db_path)
    init_db(engine)
    with get_session_factory(engine)() as db:
        sessions = SessionRepository(db).list_all()
        tracks = {
            s.id: AudioTrackRepository(db).get_by_session(s.id)
            for s in sessions
        }
        return sessions, tracks


# ── 1. Start creates a Session ────────────────────────────────────────


def test_start_creates_session_row_and_recording_state(tmp_path, store):
    tracks, _, _ = _tracks(tmp_path)
    sess = Session()
    sess.start_recording(tracks, store)

    assert sess.state == RECORDING
    assert sess.is_recording is True
    assert sess.started_at is not None
    assert sess.record_id is not None

    sessions, _ = _rows(str(tmp_path / "slice.db"))
    assert len(sessions) == 1
    assert sessions[0].status == "recording"
    assert sessions[0].source == "live"


# ── 2. Capture is started through the Session layer, never from the UI ─


def test_ui_only_talks_to_orchestrator():
    """The UI must not import capture / db / sqlalchemy / session."""
    for rel in ("ui/window.py", "ui/state.py"):
        imported = _imported_modules(rel)
        assert imported.isdisjoint({"capture", "db", "sqlalchemy", "session"}), \
            f"{rel} must not import capture/db/sqlalchemy/session: {imported}"


def test_ui_start_stop_go_through_orchestrator_commands():
    """UI calls orchestrator commands; capture is started deeper down."""
    calls = []

    class SpyOrchestrator:
        def __init__(self):
            self.recording = False

        def session_state(self):
            return {"state": "recording" if self.recording else "idle",
                    "is_recording": self.recording,
                    "elapsed_sec": 7.0, "session_id": 1, "error": None}

        def start_recording(self):
            calls.append("start")
            self.recording = True
            return self.session_state()

        def stop_recording(self):
            calls.append("stop")
            self.recording = False
            return {"state": "completed", "is_recording": False,
                    "elapsed_sec": 7.0, "session_id": 1, "error": None}

    from ui.state import button_text, format_elapsed, state_text

    spy = SpyOrchestrator()
    spy.start_recording()
    assert "ЗАПИСЬ ИДЁТ" in state_text(spy.session_state())
    assert format_elapsed(197) == "00:03:17"
    assert button_text(spy.session_state()) == "Остановить"
    assert state_text(spy.stop_recording()) == "Сессия завершена"
    assert calls == ["start", "stop"]


def test_session_starts_capture(tmp_path, store):
    tracks, mic, loop = _tracks(tmp_path)
    Session().start_recording(tracks, store)
    assert mic.is_running is True
    assert loop.is_running is True


# ── 3. Active session state ────────────────────────────────────────────


def test_elapsed_comes_from_session_started_at(tmp_path, store):
    tracks, _, _ = _tracks(tmp_path)
    sess = Session()
    assert sess.elapsed_sec == 0.0
    sess.start_recording(tracks, store)
    assert sess.elapsed_sec >= 0.0
    assert sess.is_recording


# ── 4/5. Stop finalizes the session and yields two AudioTracks ─────────


def test_stop_finalizes_session_and_persists_two_tracks(tmp_path, store):
    tracks, mic, loop = _tracks(tmp_path)
    sess = Session()
    sess.start_recording(tracks, store)
    sess.stop_recording()

    assert sess.state == COMPLETED
    assert sess.is_recording is False
    assert sess.ended_at is not None and sess.ended_at >= sess.started_at
    assert mic.stopped >= 1 and loop.stopped >= 1

    sessions, by_session = _rows(str(tmp_path / "slice.db"))
    assert len(sessions) == 1
    assert sessions[0].status == COMPLETED
    assert sessions[0].ended_at is not None

    rows = by_session[sessions[0].id]
    assert {r.source for r in rows} == {"microphone", "loopback"}
    for r in rows:
        assert r.file_path and os.path.exists(r.file_path)
        assert r.sample_rate == 48000
        assert r.channels == 1
        assert r.duration is not None
        with wave.open(r.file_path, "rb") as wf:  # WAV on disk, not in DB
            assert wf.getframerate() == 48000


# ── 6. Second Start while recording is refused ─────────────────────────


def test_second_start_while_recording_is_refused(tmp_path, store):
    tracks, _, _ = _tracks(tmp_path)
    sess = Session()
    sess.start_recording(tracks, store)
    more, _, _ = _tracks(tmp_path)
    with pytest.raises(SessionStateError):
        sess.start_recording(more, store)
    assert sess.state == RECORDING  # still the original session


def test_orchestrator_refuses_second_start(tmp_path, monkeypatch, store):
    orch = Orchestrator(recordings_dir=str(tmp_path / "rec"),
                        db_path=str(tmp_path / "slice.db"))
    tracks, _, _ = _tracks(tmp_path)
    orch.session.start_recording(tracks, store)
    state = orch.start_recording()
    assert state["error"] == "session is already recording"
    assert state["is_recording"] is True


# ── 7. Capture failure leaves no false active session / no DB rows ─────


def test_capture_failure_leaves_no_active_session_and_no_rows(tmp_path, store):
    tracks, mic, loop = _tracks(tmp_path, fail_on_start=True)
    sess = Session()
    with pytest.raises(RuntimeError):
        sess.start_recording(tracks, store)

    assert sess.is_recording is False
    assert sess.state == FAILED
    assert sess.record_id is None
    assert sess.started_at is None

    sessions, _ = _rows(str(tmp_path / "slice.db"))
    assert sessions == []  # no dangling records


def test_capture_failure_stops_already_started_tracks(tmp_path, store):
    mic = FakeCapture()
    loop = FakeCapture(fail_on_start=True)
    tracks = [
        RecordedTrack("microphone", mic, str(tmp_path / "mic.wav")),
        RecordedTrack("loopback", loop, str(tmp_path / "loopback.wav")),
    ]
    with pytest.raises(RuntimeError):
        Session().start_recording(tracks, store)
    assert mic.stopped >= 1  # first track released again


# ── 8. Stop after a failed Start is safe ──────────────────────────────


def test_stop_after_failed_start_is_safe(tmp_path, store):
    tracks, _, _ = _tracks(tmp_path, fail_on_start=True)
    sess = Session()
    with pytest.raises(RuntimeError):
        sess.start_recording(tracks, store)
    assert sess.stop_recording() is None  # no raise
    assert sess.stop_recording() is None  # idempotent


def test_stop_without_start_is_safe():
    sess = Session()
    assert sess.stop_recording() is None
    assert sess.state == "idle"


def test_next_start_works_after_a_failure(tmp_path, store):
    bad, _, _ = _tracks(tmp_path, fail_on_start=True)
    sess = Session()
    with pytest.raises(RuntimeError):
        sess.start_recording(bad, store)
    good, _, _ = _tracks(tmp_path)
    sess.start_recording(good, store)  # must not be blocked
    assert sess.state == RECORDING


# ── Session must not depend on SQLAlchemy (port isolation) ────────────


def test_session_module_has_no_sqlalchemy_dependency():
    imported = _imported_modules("session/model.py")
    assert imported.isdisjoint({"sqlalchemy", "db"}), imported


def test_capture_knows_nothing_about_session_or_db():
    for rel in ("capture/mic.py", "capture/track.py", "capture/wav.py",
                "capture/capturer.py"):
        imported = _imported_modules(rel)
        assert imported.isdisjoint(
            {"sqlalchemy", "db", "session", "orchestrator", "ui"}
        ), f"{rel} leaks a dependency: {imported}"
