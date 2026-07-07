from session.session import Session


class Orchestrator:
    def __init__(self):
        self.session = Session()

    def start_session(self):
        print("Orchestrator: starting session")
        self.session.start()