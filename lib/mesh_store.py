"""Persistent gateway-side storage for aggregated MeshOps events."""

import time

try:
    import ujson as json
except ImportError:
    import json


class MeshStore:
    def __init__(self, path="mesh-log.jsonl"):
        self.path = path

    def append(self, packet, sender_mac=None):
        record = {
            "received_ms": time.ticks_ms(),
            "source": packet.get("s"),
            "sequence": packet.get("q"),
            "kind": packet.get("k"),
            "value": packet.get("x", 0),
        }
        if sender_mac is not None:
            record["last_hop"] = "".join("%02x" % byte for byte in sender_mac)
        with open(self.path, "a") as output:
            output.write(json.dumps(record))
            output.write("\n")
