"""Sprint 16 bugfix: ProcessingWorker/QThread lifecycle tests (no Whisper).

These tests exercise the UI worker lifecycle without real transcription:
a fake orchestrator stands in for Orchestrator.process_session. They assert
the worker (a) has MainWindow as its Qt parent, (b) survives client switching
while running, (c) is cleared (self._worker = None) after a normal finish, and
(d) is cleared after an error. No DB, no audio, no GUI device needed.

NOTE: the worker's finished/deleteLater/_clear_worker slots run on the GUI
thread's event loop, so tests must pump ``app.processEvents()``. We track
completion via signal flags rather than polling the (possibly deleted) C++
thread object, which would raise once deleteLater fires.
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from unittest.mock import MagicMock

from ui.window import MainWindow, ProcessingWorker


def _app():
    return QApplication.instance() or QApplication([])


def _fake_orch(kind, delay=0.2):
    """kind: 'ok' returns a dict (after optional delay); 'err' raises."""
    orch = MagicMock()
    orch.session_state.return_value = {"is_recording": False, "state": "idle"}
    orch.list_sessions.return_value = []
    orch.list_clients.return_value = []
    orch.list_client_sessions.return_value = []
    orch.get_session.return_value = {"id": 1, "status": "dialogued", "audio_tracks": []}
    orch.get_dialogue.return_value = []

    def process_session(session_id, on_stage=None):
        if on_stage:
            on_stage("transcribing")
            on_stage("building_dialogue")
        if delay:
            time.sleep(delay)
        if kind == "err":
            raise RuntimeError("boom")
        return {"status": "dialogued"}

    orch.process_session.side_effect = process_session
    return orch


def _pump(app, deadline):
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


def test_worker_has_mainwindow_parent():
    app = _app()
    win = MainWindow(_fake_orch("ok", delay=0))
    w = ProcessingWorker(win.orchestrator, 1, parent=win)
    assert w.parent() is win
    win._worker = ProcessingWorker(win.orchestrator, 1, parent=win)
    assert isinstance(win._worker.parent(), MainWindow)


def test_client_switch_during_processing_keeps_worker_running():
    app = _app()
    win = MainWindow(_fake_orch("ok", delay=0.6))
    win.refresh_client_list()
    win._start_processing(1)
    worker = win._worker
    assert worker.isRunning()

    # While the worker runs, switch clients and pump the event loop so stage
    # signals dispatch. Client switching must NOT replace the worker reference
    # while processing is underway. Once the worker finishes and clears the
    # reference, we stop switching (that is the expected end state).
    switched = 0
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if win._worker is None:
            break
        before = win._worker
        win.on_client_selected(
            win.client_list.item(0) if win.client_list.count() else None, None)
        win._show_client_sessions(None)
        win._select_session(1)
        app.processEvents()
        if win._worker is None:
            break
        assert win._worker is before, "client switch replaced the worker"
        time.sleep(0.01)
        switched += 1
    assert switched > 0, "worker finished before any switch (timing too short)"
    assert win._worker is None or win._worker is worker

    # Let finished/deleteLater/_clear_worker dispatch; reference must clear.
    _pump(app, time.time() + 2.0)
    assert win._worker is None


def test_normal_finish_clears_worker_reference():
    app = _app()
    win = MainWindow(_fake_orch("ok", delay=0.1))
    win._start_processing(1)
    assert win._worker is not None
    _pump(app, time.time() + 3.0)
    assert win._worker is None, "self._worker must be None after normal finish"


def test_error_finish_clears_worker_reference():
    app = _app()
    win = MainWindow(_fake_orch("err", delay=0.1))
    win._start_processing(1)
    assert win._worker is not None
    _pump(app, time.time() + 3.0)
    assert win._worker is None, "self._worker must be None after error"
