from json import load as json_load

class Settings:
    def __init__(self, path="settings.json") -> None:
        self.load_from_file(path=path)

    def load_from_file(self, path):
        with open(path, "r") as f:
            settings_data = json_load(f)

        self.mode = settings_data["mode"]
        self.ssid = settings_data["ssid"]
        self.password = settings_data["password"]
