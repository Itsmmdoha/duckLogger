"""Persistent gateway-side storage for aggregated MeshOps events."""

import time

try:
    import ujson as json
except ImportError:
    import json


def _ticks_ms():
    try:
        return time.ticks_ms()
    except AttributeError:
        return int(time.time() * 1000)


class MeshStore:
    def __init__(self, path="mesh-log.jsonl"):
        self.path = path

    def append(self, packet, sender_mac=None):
        record = {
            "gateway_received_ms": _ticks_ms(),
            "network_id": packet.get("n", ""),
            "source": packet.get("s"),
            "boot_id": packet.get("b", "legacy"),
            "sequence": packet.get("q"),
            "kind": packet.get("k"),
            "value": packet.get("x", 0),
            "hop_count": packet.get("h", 0),
        }
        if sender_mac is not None:
            record["last_hop"] = "".join("%02x" % byte for byte in sender_mac)
        with open(self.path, "a") as output:
            output.write(json.dumps(record))
            output.write("\n")
        return record
