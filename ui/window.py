"""Main window — commands and rendering only.

The UI knows NOTHING about Capture, SQLite or SQLAlchemy: it sends commands
to the Orchestrator and renders the state / session data it gets back. The
elapsed time comes from the Session state (``elapsed_sec``); the QTimer here
only triggers a repaint, it does not measure anything.

Sprint 13: a read-only Session Viewer. A list of sessions on the left;
selecting one shows its details and the built Dialogue (no editing).

Sprint 14: after Stop, post-stop processing (transcribe -> dialogue) runs
automatically in a background QThread so the GUI never blocks on Whisper.
The window refuses to close while processing is in flight (closing mid-run
would interrupt an unsafe synchronous call); WAV/DB stay consistent and a
re-run is idempotent. Stage signals let the user see progress (transcribing
-> building_dialogue) without polling the DB; no percentages (per scope).

Sprint 16: Client layer. The viewer is two-level: a client list (Тест 001…)
on top, the selected client's sessions below, and details/Dialogue on the
right. Before recording, the user picks an existing client or creates a new
one; the new session is bound to that client. Sessions with no client
("Без клиента") remain visible after normal clients.
"""

from PySide6.QtCore import QTimer, QThread, Signal
from PySide6.QtWidgets import (
    QMainWindow,
    QPushButton,
    QLabel,
    QListWidget,
    QTextEdit,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QMessageBox,
    QInputDialog,
    QComboBox,
    QDialog,
    QFormLayout,
    QLineEdit,
)

from ui.state import (
    button_text,
    client_label,
    client_session_groups,
    dialogue_text,
    session_detail_text,
    session_row_text,
    state_text,
)


class ProcessingWorker(QThread):
    """Runs Orchestrator.process_session off the GUI thread."""

    started = Signal()
    transcribing = Signal()
    building_dialogue = Signal()
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, orchestrator, session_id, parent=None):
        super().__init__(parent)
        self._orch = orchestrator
        self._session_id = session_id

    def run(self):
        try:
            self.started.emit()
            result = self._orch.process_session(
                self._session_id,
                on_stage=self._emit_stage,
            )
            self.finished.emit(result)
        except Exception as exc:  # surface, never crash the GUI thread
            self.error.emit(str(exc))

    def _emit_stage(self, stage: str):
        if stage == "transcribing":
            self.transcribing.emit()
        elif stage == "building_dialogue":
            self.building_dialogue.emit()


class _ClientPickDialog(QDialog):
    """Modal picker: choose an existing client or create a new one."""

    def __init__(self, orchestrator, parent=None):
        super().__init__(parent)
        self._orch = orchestrator
        self.selected_client_id = None
        self.setWindowTitle("Выберите клиента")
        self.resize(360, 160)

        self.combo = QComboBox(self)
        self._refresh_clients()

        self.new_name = QLineEdit(self)
        self.new_name.setPlaceholderText("Новый клиент: имя (напр. Тест)")

        self.ok_btn = QPushButton("Начать запись", self)
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn = QPushButton("Отмена", self)
        self.cancel_btn.clicked.connect(self.reject)

        layout = QFormLayout(self)
        layout.addRow("Клиент:", self.combo)
        layout.addRow("Или новый:", self.new_name)
        row = QHBoxLayout()
        row.addWidget(self.ok_btn)
        row.addWidget(self.cancel_btn)
        layout.addRow(row)

    def _refresh_clients(self):
        self.combo.clear()
        self.combo.addItem("— выбрать существующего —", None)
        for c in self._orch.list_clients():
            self.combo.addItem(client_label(c), c["id"])

    def accept(self):
        name = (self.new_name.text() or "").strip()
        if name:
            client = self._orch.create_client(name)
            self.selected_client_id = client["id"]
        else:
            self.selected_client_id = self.combo.currentData()
        super().accept()


class MainWindow(QMainWindow):
    def __init__(self, orchestrator):
        super().__init__()
        self.orchestrator = orchestrator
        self._worker = None  # type: ignore[var-annotated]
        self._selected_client_id = None  # type: ignore[var-annotated]
        self._session_ids = []  # type: ignore[var-annotated]

        self.setWindowTitle("Psych AI")
        self.resize(900, 600)

        # --- Recording control (unchanged behaviour) --- #
        self.button = QPushButton("Начать запись", self)
        self.button.clicked.connect(self.toggle_recording)
        self.status = QLabel("Готов к записи", self)
        self.status.resize(400, 60)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)

        # --- Sprint 16: client -> session -> detail viewer --- #
        self.client_list = QListWidget(self)
        self.client_list.currentItemChanged.connect(self.on_client_selected)
        self.session_list = QListWidget(self)
        self.session_list.currentItemChanged.connect(self.on_session_selected)
        self.session_detail = QLabel("Выберите сессию", self)
        self.session_detail.setWordWrap(True)
        self.dialogue_view = QTextEdit(self)
        self.dialogue_view.setReadOnly(True)

        left = QVBoxLayout()
        left.addWidget(QLabel("Клиенты"))
        left.addWidget(self.client_list, 1)
        left.addWidget(QLabel("Сессии"))
        left.addWidget(self.session_list, 2)

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

        self.refresh_client_list()

    # ------------------------------------------------------------------ #
    # Commands (recording)
    # ------------------------------------------------------------------ #
    def toggle_recording(self):
        if self.orchestrator.session_state().get("is_recording"):
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        dlg = _ClientPickDialog(self.orchestrator, self)
        if dlg.exec() != QDialog.Accepted:
            return
        client_id = dlg.selected_client_id
        state = self.orchestrator.start_recording(client_id=client_id)
        self.render(state)
        if state.get("is_recording"):
            self._timer.start()

    def stop_recording(self):
        self._timer.stop()
        state = self.orchestrator.stop_recording()
        self.render(state)
        self.refresh_client_list()
        session_id = state.get("session_id")
        if session_id is not None and state.get("state") == "completed":
            self._start_processing(session_id)

    # ------------------------------------------------------------------ #
    # Sprint 14: automatic post-stop processing (background)
    # ------------------------------------------------------------------ #
    def _start_processing(self, session_id: int):
        self.status.setText("Обработка… (транскрипция и Dialogue)")
        self._worker = ProcessingWorker(self.orchestrator, session_id, parent=self)
        self._worker.started.connect(lambda: self.status.setText("Обработка…"))
        self._worker.transcribing.connect(
            lambda: self.status.setText("Транскрипция…"))
        self._worker.building_dialogue.connect(
            lambda: self.status.setText("Построение Dialogue…"))
        self._worker.finished.connect(
            lambda res: self._on_processing_finished(session_id, res))
        self._worker.error.connect(
            lambda err: self.status.setText(f"Ошибка обработки: {err}"))
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.error.connect(self._worker.deleteLater)
        self._worker.finished.connect(self._clear_worker)
        self._worker.error.connect(self._clear_worker)
        self._worker.start()

    def _on_processing_finished(self, session_id: int, result: dict):
        status = result.get("status")
        if status == "dialogued":
            self.status.setText("Готово: Dialogue построен")
        elif status in ("transcription_failed", "dialogue_failed",
                        "transcribed_partial"):
            self.status.setText(f"Обработка завершена с ошибкой: {status}")
        else:
            self.status.setText(f"Обработка завершена: {status}")
        self.refresh_client_list()
        self._select_session(session_id)

    def _clear_worker(self):
        """Drop the Python reference to the (already deleteLater'd) worker.

        Called only after the worker has finished/errored, never while the
        thread is still running. Keeps ``self._worker`` from dangling on a
        destroyed C++ object and lets ``closeEvent`` report a clean state.
        """
        self._worker = None

    # ------------------------------------------------------------------ #
    # Client / session viewer (read-only, two-level)
    # ------------------------------------------------------------------ #
    def refresh_client_list(self):
        self.client_list.blockSignals(True)
        self.client_list.clear()
        self._client_ids = []
        sessions = self.orchestrator.list_sessions()
        for grp in client_session_groups(sessions):
            self._client_ids.append(grp["client_id"])
            self.client_list.addItem(grp["label"])
        self.client_list.blockSignals(False)
        # Keep current selection if still valid.
        if self._selected_client_id is not None:
            self._show_client_sessions(self._selected_client_id)
        else:
            self.session_list.clear()

    def on_client_selected(self, current, _previous):
        if current is None:
            return
        idx = self.client_list.row(current)
        if idx < 0 or idx >= len(self._client_ids):
            return
        self._selected_client_id = self._client_ids[idx]
        self._show_client_sessions(self._selected_client_id)

    def _show_client_sessions(self, client_id):
        self.session_list.blockSignals(True)
        self.session_list.clear()
        self._session_ids = []
        if client_id is None:
            sessions = [s for s in self.orchestrator.list_sessions()
                        if s.get("client_id") is None]
        else:
            sessions = self.orchestrator.list_client_sessions(client_id)
        for s in sessions:
            self._session_ids.append(s["id"])
            self.session_list.addItem(session_row_text(s))
        self.session_list.blockSignals(False)

    def on_session_selected(self, current, _previous):
        if current is None:
            return
        idx = self.session_list.row(current)
        if idx < 0 or idx >= len(self._session_ids):
            return
        self._select_session(self._session_ids[idx])

    def _select_session(self, session_id: int):
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

    # ------------------------------------------------------------------ #
    # Window lifecycle: never close mid-processing
    # ------------------------------------------------------------------ #
    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self, "Обработка не завершена",
                "Идёт обработка сессии. Дождитесь завершения перед выходом.",
            )
            event.ignore()
            return
        event.accept()
