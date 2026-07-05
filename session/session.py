class Session:
    def __init__(self):
        self.active = False

    def start(self):
        self.active = True
        print("Session object started")