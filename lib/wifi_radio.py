def start(settings=None, channel=None):
    if settings is None:
        from settings import Settings
        settings = Settings()
    if settings.mode == "ap":
        from access_point import AccessPoint
        ap = AccessPoint(ssid=settings.ssid, password=settings.password)
        return ap.start(channel=channel)
    else:
        from wifi import WifiNetwork
        wifi = WifiNetwork(ssid=settings.ssid, password=settings.password)
        return wifi.connect()
