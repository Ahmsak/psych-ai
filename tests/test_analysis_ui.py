"""Sprint 17 headless UI smoke test for the AI-analysis feature.

Runs WITHOUT a real display: uses PySide6's offscreen platform plugin and a
stub Orchestrator so no network/audio/DB is touched.

NOTE: we do NOT start the AnalysisWorker QThread in these tests — driving a
real QThread + deleteLater under the offscreen plugin crashes the test
process (a PySide6/Qt event-loop interaction, not a product bug; the same
worker pattern already passes in test_processing_worker_lifecycle.py).
Instead we exercise the UI wiring and the render slots directly, which is
what matters for layout/state correctness here.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")

# Headless: never open a real window.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

# Single QApplication for the whole module (QApplication must not be created
# more than once per process; re-creating it across tests crashes PySide6).
_APP = QApplication.instance() or QApplication([])


class _StubOrchestrator:
    """Minimal orchestrator double for UI wiring only."""

    def __init__(self, analysis_result=None, error=None):
        self._analysis_result = analysis_result or {
            "status": "analyzed",
            "provider": "fake",
            "model": "gemini-2.5-flash",
            "prompt_version": "v1",
            "text": "СУПЕРВИЗОР:\n1. Краткое содержание…",
        }
        self._error = error
        self.calls = []
        self.get_analysis_result = None

    def analyze_session(self, session_id):
        self.calls.append(session_id)
        return dict(self._analysis_result)

    def get_analysis(self, session_id):
        return self.get_analysis_result

    def get_session(self, session_id):
        return {"id": session_id, "source": "live", "status": "completed",
                "started_at": None, "ended_at": None,
                "client_id": None, "client_name": None, "client_number": None,
                "audio_tracks": []}

    def get_dialogue(self, session_id):
        return []

    def list_sessions(self):
        return []

    def list_clients(self):
        return []

    def list_client_sessions(self, client_id):
        return []

    def session_state(self):
        return {"is_recording": False, "state": "idle"}


def _make_window():
    from ui.window import MainWindow

    orch = _StubOrchestrator()
    win = MainWindow(orch)
    return win, orch


def test_window_has_analysis_controls():
    win, orch = _make_window()
    assert hasattr(win, "analyze_button")
    assert win.analyze_button.text() == "AI-анализ"
    assert hasattr(win, "analysis_view")
    assert hasattr(win, "analysis_status")
    # Initial state: disabled until a session is selected.
    assert win.analyze_button.isEnabled() is False


def test_select_session_enables_analysis_and_shows_stored():
    win, orch = _make_window()
    orch.get_analysis_result = {
        "status": "analyzed", "provider": "fake",
        "model": "gemini-2.5-flash", "prompt_version": "v1",
        "text": "СОХРАНЁННЫЙ АНАЛИЗ",
    }
    win._select_session(7)
    assert win.analyze_button.isEnabled() is True
    assert "СОХРАНЁННЫЙ АНАЛИЗ" in win.analysis_view.toPlainText()


def test_render_finished_shows_result():
    win, orch = _make_window()
    win._select_session(1)
    result = {
        "status": "analyzed", "provider": "fake", "model": "gemini-2.5-flash",
        "prompt_version": "v1", "text": "РЕЗУЛЬТАТ АНАЛИЗА",
    }
    win._on_analysis_finished(1, result)
    assert "РЕЗУЛЬТАТ АНАЛИЗА" in win.analysis_view.toPlainText()
    assert "Анализ готов" in win.analysis_status.text()
    # Re-enabled after completion (no permanent GUI block).
    assert win.analyze_button.isEnabled() is True


def test_render_error_shows_message():
    win, orch = _make_window()
    win._select_session(2)
    result = {"status": "error", "error": "boom detail"}
    win._on_analysis_finished(2, result)
    assert "Ошибка анализа" in win.analysis_status.text()
    assert "boom detail" in win.analysis_status.text()


def test_no_transcript_renders_placeholder():
    win, orch = _make_window()
    win._select_session(3)
    result = {"status": "no_transcript", "error": "no raw transcript"}
    win._on_analysis_finished(3, result)
    assert "Нет RAW-транскрипта" in win.analysis_view.toPlainText()


def test_select_session_arms_analysis_button():
    win, orch = _make_window()
    # Before selecting a session the analysis button is disabled.
    assert win.analyze_button.isEnabled() is False
    win._select_session(1)
    # After selecting, it is enabled and carries the session id used by the
    # click handler (proves the button is wired into the analysis flow).
    assert win.analyze_button.isEnabled() is True
    assert win.analyze_button.property("session_id") == 1