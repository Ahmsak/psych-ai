"""Main window — commands and rendering only.

The UI knows NOTHING about Capture, SQLite or SQLAlchemy: it sends two
commands to the Orchestrator and renders the state it gets back. The
elapsed time comes from the Session state (``elapsed_sec``); the QTimer
here only triggers a repaint, it does not measure anything.
"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QMainWindow,
    QPushButton,
    QLabel
)

from ui.state import button_text, state_text


class MainWindow(QMainWindow):
    def __init__(self, orchestrator):
        super().__init__()
        self.orchestrator = orchestrator

        self.setWindowTitle("Psych AI")
        self.resize(800, 600)

        self.button = QPushButton("Начать запись", self)
        self.button.move(20, 20)
        self.button.clicked.connect(self.toggle_recording)
        self.status = QLabel("Готов к записи", self)
        self.status.resize(400, 60)
        self.status.move(20, 60)

        # Repaint only; the elapsed value itself comes from the Session.
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)

    # ------------------------------------------------------------------ #
    # Commands
    # ------------------------------------------------------------------ #
    def toggle_recording(self):
        if self.orchestrator.session_state().get("is_recording"):
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        state = self.orchestrator.start_recording()
        self.render(state)
        if state.get("is_recording"):
            self._timer.start()

    def stop_recording(self):
        self._timer.stop()
        self.render(self.orchestrator.stop_recording())

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #
    def refresh(self):
        self.render(self.orchestrator.session_state())

    def render(self, state: dict):
        self.status.setText(state_text(state))
        self.button.setText(button_text(state))
