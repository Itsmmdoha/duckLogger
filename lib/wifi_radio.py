from settings import Settings

settings = Settings()

def start():
    if settings.mode == "ap":
        from access_point import AccessPoint
        ap = AccessPoint(ssid=settings.ssid, password=settings.password)
        ap.start()
    else:
        from wifi import WifiNetwork
        wifi = WifiNetwork(ssid=settings.ssid, password=settings.password)
        wifi.connect()
