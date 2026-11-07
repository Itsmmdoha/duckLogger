"""ESP-NOW implementation of the MeshOps radio transport."""

from mesh_transport import BROADCAST, RadioTransport


class EspNowTransport(RadioTransport):
    def __init__(self, channel, peer_key, peer_addresses=()):
        self.channel = channel
        self.peer_key = peer_key
        self.peer_addresses = tuple(peer_addresses)
        self.sta = None
        self.radio = None
        self.peers = []

    def start(self):
        # Hardware modules stay lazy so the mesh core remains CPython-testable.
        import espnow
        import network

        self._network = network
        self.sta = network.WLAN(network.STA_IF)
        self.sta.active(True)
        if self.sta.isconnected():
            self.sta.disconnect()
        try:
            self.sta.config(channel=self.channel)
        except OSError:
            pass

        self.radio = espnow.ESPNow()
        self.radio.active(True)
        if self.peer_key:
            self.radio.set_pmk(self.peer_key)
        self._add_peer(BROADCAST, encrypt=False)
        # Encrypted receive requires the sender and its LMK to be registered
        # locally before its first packet arrives.
        for address in self.peer_addresses:
            self._add_peer(address, encrypt=True)
        return self.sta.config("mac")

    def stop(self):
        if self.radio is not None:
            self.radio.active(False)

    def _add_peer(self, address, encrypt=True):
        if address in self.peers:
            return
        try:
            if encrypt and len(self.peer_key) == 16:
                self.radio.add_peer(
                    address,
                    lmk=self.peer_key,
                    channel=0,
                    ifidx=self._network.STA_IF,
                    encrypt=True,
                )
            else:
                self.radio.add_peer(address)
        except OSError:
            # ESP-NOW reports an error if the peer already exists.
            pass
        self.peers.append(address)

    def send(self, address, payload):
        self._add_peer(address, encrypt=(address != BROADCAST))
        self.radio.send(address, payload, False)
        return True

    def recv(self):
        return self.radio.irecv(0)

    def status(self):
        mac = self.sta.config("mac") if self.sta is not None else b""
        return {
            "type": "espnow",
            "channel": self.channel,
            "mac": ":".join("%02x" % byte for byte in mac),
            "peers": len(self.peers),
        }
