from PySide6.QtWidgets import QApplication

from ui.window import MainWindow


class App:
    def __init__(self):
        self.qt_app = QApplication([])
        self.window = MainWindow()

    def run(self):
        self.window.show()
        self.qt_app.exec()