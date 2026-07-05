from PySide6.QtWidgets import (
    QMainWindow,
    QPushButton,
    QLabel
)


class MainWindow(QMainWindow):
    def __init__(self, session):
        super().__init__()
        self.session = session

        self.setWindowTitle("Psych AI")
        self.resize(800, 600)

        button = QPushButton("Start Session", self)
        button.move(20, 20)
        button.clicked.connect(self.start_session)
        self.status = QLabel("Status: Ready", self)
        self.status.move(20, 60)


    def start_session(self):
        self.session.start()
        self.status.setText("Status: Session started")