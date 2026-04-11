import network
import time


class WiFiNetwork:
    def __init__(self, ssid: str, password: str = ""):
        self.ssid = ssid
        self.password = password
        self.sta = network.WLAN(network.STA_IF)

    def connect(self, timeout: int = 10):
        if not self.sta.active():
            self.sta.active(True)

        if self.sta.isconnected():
            print("Already connected")
            return self.sta.ifconfig()[0]

        print("Connecting to WiFi:", self.ssid)
        self.sta.connect(self.ssid, self.password)

        start = time.time()
        while not self.sta.isconnected():
            if time.time() - start > timeout:
                print("Connection timeout")
                return None
            time.sleep(0.5)

        ip = self.sta.ifconfig()[0]

        print("Connected!")
        print("SSID:", self.ssid)
        print("IP:", ip)

        return ip

    def disconnect(self):
        if self.sta.isconnected():
            self.sta.disconnect()
            print("Disconnected")

    def is_connected(self):
        return self.sta.isconnected()

    def get_ip(self):
        if self.sta.isconnected():
            return self.sta.ifconfig()[0]
        return None
