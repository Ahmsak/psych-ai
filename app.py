from PySide6.QtWidgets import QApplication

from ui.window import MainWindow

from session.session import Session


class App:
    def __init__(self):
        self.qt_app = QApplication([])
        self.session = Session()
        self.window = MainWindow(self.session)
        

    def run(self):
        self.window.show()
        self.qt_app.exec()