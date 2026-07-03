class App:
    def __init__(self):
        self.name = "Psych AI"

        print("App created")

    def show_info(self):
        print(f"Application: {self.name}")

    def run(self):
        self.show_info()
        print(f"{self.name} started")