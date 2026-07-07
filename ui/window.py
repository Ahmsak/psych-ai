from PySide6.QtWidgets import (
    QMainWindow,
    QPushButton,
    QLabel
)


class MainWindow(QMainWindow):
    def __init__(self, orchestrator):
        super().__init__()
        self.orchestrator = orchestrator

        self.setWindowTitle("Psych AI")
        self.resize(800, 600)

        button = QPushButton("Start Session", self)
        button.move(20, 20)
        button.clicked.connect(self.start_session)
        self.status = QLabel("Status: Ready", self)
        self.status.move(20, 60)


    def start_session(self):
        self.orchestrator.start_session()
        self.status.setText("Status: Session started")