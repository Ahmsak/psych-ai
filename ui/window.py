"""Main window — commands and rendering only.

The UI knows NOTHING about Capture, SQLite or SQLAlchemy: it sends commands
to the Orchestrator and renders the state / session data it gets back. The
elapsed time comes from the Session state (``elapsed_sec``); the QTimer here
only triggers a repaint, it does not measure anything.

Sprint 13: a read-only Session Viewer. A list of sessions on the left;
selecting one shows its details and the built Dialogue (no editing).
"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QMainWindow,
    QPushButton,
    QLabel,
    QListWidget,
    QTextEdit,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
)

from ui.state import (
    button_text,
    dialogue_text,
    session_detail_text,
    session_row_text,
    state_text,
)


class MainWindow(QMainWindow):
    def __init__(self, orchestrator):
        super().__init__()
        self.orchestrator = orchestrator

        self.setWindowTitle("Psych AI")
        self.resize(900, 600)

        # --- Recording control (unchanged behaviour) ---
        self.button = QPushButton("Начать запись", self)
        self.button.clicked.connect(self.toggle_recording)
        self.status = QLabel("Готов к записи", self)
        self.status.resize(400, 60)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)

        # --- Sprint 13: session viewer (read-only) ---
        self.session_list = QListWidget(self)
        self.session_list.currentItemChanged.connect(self.on_session_selected)
        self.session_detail = QLabel("Выберите сессию", self)
        self.session_detail.setWordWrap(True)
        self.dialogue_view = QTextEdit(self)
        self.dialogue_view.setReadOnly(True)

        # Layout
        left = QVBoxLayout()
        left.addWidget(QLabel("Сессии"))
        left.addWidget(self.session_list, 1)

        right = QVBoxLayout()
        right.addWidget(QLabel("Детали сессии"))
        right.addWidget(self.session_detail)
        right.addWidget(QLabel("Dialogue"))
        right.addWidget(self.dialogue_view, 2)

        lists = QHBoxLayout()
        lists.addLayout(left, 1)
        lists.addLayout(right, 2)

        main = QVBoxLayout()
        main.addWidget(self.button)
        main.addWidget(self.status)
        main.addLayout(lists, 1)

        container = QWidget(self)
        container.setLayout(main)
        self.setCentralWidget(container)

        # Initial load of the session list.
        self.refresh_session_list()

    # ------------------------------------------------------------------ #
    # Commands (recording) — unchanged
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
        # A new session may now exist — refresh the viewer list.
        self.refresh_session_list()

    # ------------------------------------------------------------------ #
    # Session viewer (read-only)
    # ------------------------------------------------------------------ #
    def refresh_session_list(self):
        self.session_list.blockSignals(True)
        self.session_list.clear()
        self._session_ids = []
        for s in self.orchestrator.list_sessions():
            self._session_ids.append(s["id"])
            self.session_list.addItem(session_row_text(s))
        self.session_list.blockSignals(False)

    def on_session_selected(self, current, _previous):
        if current is None:
            return
        idx = self.session_list.row(current)
        if idx < 0 or idx >= len(self._session_ids):
            return
        session_id = self._session_ids[idx]
        session = self.orchestrator.get_session(session_id)
        if session is None:
            self.session_detail.setText(f"Сессия {session_id} не найдена")
            self.dialogue_view.setPlainText("")
            return
        self.session_detail.setText(session_detail_text(session))
        utterances = self.orchestrator.get_dialogue(session_id)
        self.dialogue_view.setPlainText(dialogue_text(utterances))

    # ------------------------------------------------------------------ #
    # Recording render
    # ------------------------------------------------------------------ #
    def refresh(self):
        self.render(self.orchestrator.session_state())

    def render(self, state: dict):
        self.status.setText(state_text(state))
        self.button.setText(button_text(state))
