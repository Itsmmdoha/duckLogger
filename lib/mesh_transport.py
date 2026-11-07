"""Small radio interface shared by MeshOps mesh transports."""

BROADCAST = b"\xff\xff\xff\xff\xff\xff"


class RadioTransport:
    """Interface implemented by hardware transports and test doubles."""

    def start(self):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

    def send(self, address, payload):
        raise NotImplementedError

    def recv(self):
        raise NotImplementedError

    def status(self):
        return {}
