from PySide6.QtWidgets import QApplication

from ui.window import MainWindow

#from session.session import Session

from orchestrator.orchestrator import Orchestrator


class App:
    def __init__(self):
        self.qt_app = QApplication([])
        self.orchestrator = Orchestrator()
        #self.session = Session()
        self.window = MainWindow(self.orchestrator)
        

    def run(self):
        self.window.show()
        self.qt_app.exec()