import sys
import types

from espnow_transport import EspNowTransport
from mesh_transport import BROADCAST


class FakeWLAN:
    def __init__(self, interface):
        self.interface = interface
        self.channel = None
        self.enabled = False

    def active(self, enabled):
        self.enabled = enabled

    def isconnected(self):
        return False

    def config(self, *args, **kwargs):
        if "channel" in kwargs:
            self.channel = kwargs["channel"]
        if args == ("mac",):
            return bytes.fromhex("020000000001")


class FakeRadio:
    def __init__(self):
        self.enabled = False
        self.pmk = None
        self.peers = []
        self.sent = []

    def active(self, enabled):
        self.enabled = enabled

    def set_pmk(self, key):
        self.pmk = key

    def add_peer(self, address, **kwargs):
        self.peers.append((address, kwargs))

    def send(self, address, payload, sync):
        self.sent.append((address, payload, sync))

    def irecv(self, timeout):
        return None, None


def test_espnow_transport_owns_hardware_setup_and_peers(monkeypatch):
    wlan = FakeWLAN(0)
    radio = FakeRadio()
    network = types.SimpleNamespace(STA_IF=0, WLAN=lambda interface: wlan)
    espnow = types.SimpleNamespace(ESPNow=lambda: radio)
    monkeypatch.setitem(sys.modules, "network", network)
    monkeypatch.setitem(sys.modules, "espnow", espnow)

    configured_peer = bytes.fromhex("020000000003")
    transport = EspNowTransport(
        6, b"0123456789abcdef", (configured_peer,)
    )
    assert transport.start() == bytes.fromhex("020000000001")
    assert wlan.channel == 6
    assert radio.pmk == b"0123456789abcdef"
    assert radio.peers[0][0] == BROADCAST
    assert radio.peers[1][0] == configured_peer
    assert radio.peers[1][1]["encrypt"] is True

    peer = bytes.fromhex("020000000002")
    transport.send(peer, b"payload")
    assert radio.sent == [(peer, b"payload", False)]
    assert radio.peers[2][1]["encrypt"] is True
    assert transport.status()["peers"] == 3

    transport.stop()
    assert radio.enabled is False
