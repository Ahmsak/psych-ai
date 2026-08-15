"""Sprint 14 UI tests: automatic post-stop processing wiring (no real audio,
no Whisper). Uses a fake Orchestrator so the GUI wiring (worker start,
non-blocking, closeEvent guard) is verified without a 26s model run.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from PySide6.QtGui import QCloseEvent

from ui.window import MainWindow


class FakeOrchestrator:
    """Minimal Orchestrator double: no recording, no Whisper."""

    def __init__(self):
        self._recording = False
        self.process_calls = 0
        self.last_processed = None

    def session_state(self):
        return {
            "state": "recording" if self._recording else "completed",
            "is_recording": self._recording,
            "elapsed_sec": 0,
            "session_id": 1,
            "error": None,
        }

    def start_recording(self):
        self._recording = True
        return self.session_state()

    def stop_recording(self):
        self._recording = False
        return {"state": "completed", "session_id": 1, "is_recording": False}

    def list_sessions(self):
        return [{"id": 1, "source": "live", "status": "completed",
                 "started_at": None, "ended_at": None}]

    def get_session(self, sid):
        return {"id": sid, "source": "live", "status": "dialogued",
                "started_at": None, "ended_at": None, "audio_tracks": []}

    def get_dialogue(self, sid):
        return [{"speaker": "psychologist", "start": 0.0, "end": 1.0,
                 "text": "тест", "source": "microphone", "confidence": 0.9}]

    def process_session(self, session_id=None, on_stage=None):
        if on_stage is not None:
            on_stage("transcribing")
            on_stage("building_dialogue")
        self.process_calls += 1
        self.last_processed = session_id
        return {"status": "dialogued", "utterances": 4}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _pump(app, win, limit=200):
    for _ in range(limit):
        app.processEvents()
        if win._worker is None or not win._worker.isRunning():
            break
    # Drain the event queue so queued `finished` signals reach their slots
    # (the worker may have stopped but its signal is still in the queue).
    for _ in range(50):
        app.processEvents()


def test_stop_recording_starts_background_processing(app, monkeypatch):
    monkeypatch.setattr("ui.window.QMessageBox.information", lambda *a, **k: None)
    orch = FakeOrchestrator()
    win = MainWindow(orch)
    win.stop_recording()
    assert win._worker is not None
    assert win._worker.isRunning()
    _pump(app, win)
    assert orch.process_calls == 1
    assert orch.last_processed == 1
    assert "Готово" in win.status.text()
    # Dialogue auto-selected and rendered after finished.
    assert "тест" in win.dialogue_view.toPlainText()


def test_close_event_blocked_while_processing(app, monkeypatch):
    monkeypatch.setattr("ui.window.QMessageBox.information", lambda *a, **k: None)
    orch = FakeOrchestrator()
    win = MainWindow(orch)
    win.stop_recording()
    assert win._worker is not None and win._worker.isRunning()
    ce = QCloseEvent()
    win.closeEvent(ce)
    # Closing mid-processing must be refused.
    assert ce.isAccepted() is False
    _pump(app, win)
