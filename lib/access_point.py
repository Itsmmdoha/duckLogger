import network


class AccessPoint:
    def __init__(self, ssid: str, password: str = ""):
        self.ssid = ssid
        self.password = password
        self.ap = network.WLAN(network.AP_IF)

    def start(self):
        if not self.ap.active():
            self.ap.active(True)

        # Decide mode based on password
        if self.password:
            # Secured network (WPA2)
            self.ap.config(
                essid=self.ssid,
                password=self.password,
                authmode=3
            )
        else:
            # Open network
            self.ap.config(
                essid=self.ssid,
                authmode=0
            )

        ip = self.ap.ifconfig()[0]

        print("AP started")
        print("SSID:", self.ssid)
        print("Mode:", "OPEN" if not self.password else "WPA2")
        print("IP:", ip)

        return ip

    def stop(self):
        if self.ap.active():
            self.ap.active(False)
            print("AP stopped")
